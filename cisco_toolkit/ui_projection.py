"""ui_projection/1 -- the ONE typed projection from a snapshot to what a screen shows (D9).

"Facts in Python, geometry in the browser." Every verdict, count, rollup, denominator, severity band
and evidence state a UI renders is decided HERE, from the engine's owners, and published in one
schema-tagged payload. The browser only lays out, sorts, filters and draws; it never aggregates, never
re-derives a headline number and never turns an absence into a value.

Slice 1 covers two screens:

* ``overview`` -- the canonical headline facts (:data:`ssot.CANONICAL_FACTS`), the fleet-health
  scoring state, the executive-brief axes (and the registered axes the brief does not carry), each
  axis with how many devices it could not assess out of how many, read from its producer
  (:data:`AXIS_UNASSESSED`; not_collected, never 0, where the producer stores no such count, where it covers one
  layer of several, or where a listed collection blind spot leaves a zero unproven), the
  top-gating list, the posture statement, and the lifecycle band partition in its canonical order;
* ``trust`` -- the live schema census, the failed-phase record, the published coverage matrix, the
  unknown-evidence summary, the SSOT self-verification, the analysis-input gap summary (per input of the
  engine's per-device risk register: the inventory devices it could not assess, out of the inventory), and
  the projection's own stated limitations;

plus an ``engine`` block naming the snapshot schema and producer versions, and (G41) the SHA-256 and byte length of
the exact bytes the snapshot was parsed from, so every pointer names the byte string it resolves in. Only the reader
that holds those bytes can bind them (``protocol_assurance.bind_snapshot_json_bytes``); a snapshot handed over already
parsed names no file (``not_collected``), and the projection never hashes a re-serialisation in its place.

Slice 2 adds the row screens:

* ``inventory`` -- device rows (the ``devices`` map joined with the ``collection_completeness`` blind spots,
  so an unreached device is never dropped), VLAN cutover rows with their stored L3 gateway rows (G16: switch, SVI
  address, FHRP role, object tracking and the sole-gateway risk), endpoint rows with their shared-IP and
  dual-homed lists, and the cable-map peers nobody collected; every list in a stable order with a total
  from its owner, ready to be paged;
* ``findings`` -- the engine's punch-list rows, with the severity vocabulary, the remediation the engine
  links and the show command it cites, and nothing it does not publish; and their facet totals (G21): row
  counts by severity and by category from the owner's partition of the stored rows
  (``analyze.compute_punchlist_facets``), admitted only when they place every row exactly once, never claimed
  complete over a category whose source section (``analyze.PUNCH_CATEGORY_SECTION``) is incomplete, and, as a
  roster list with its own state, by inventory device from the per-device rollup (the G09 fold), never a
  second count; and (G24) the stored cross-layer correlation rows, each host joined by exact name to its
  collected device record and to the health deduction the row drives there (the scorer's own reference to the
  row, and the line item carrying the row's label), never recomputed, an unjoinable or repeated host unverified
  rather than dropped;
* :func:`project_device` -- one standalone device page per host (identity, physical, blind-spot record,
  health, lifecycle, dossier, coverage, interfaces, links, routes, routing neighbours with each neighbour's
  collected peer host resolved through the topology's one address index (G17), security checks,
  native-VLAN mismatches, remediation, NRFU cases, the punch-list rows and endpoints naming it, and the stored
  failure-impact and structural-link rows naming it -- selected, never re-simulated; a device with no
  simulation row is a blind spot, never "no impact").

Every standalone document (the fleet payload, a ``DeviceDocument``, a ``PathDocument``) also carries ``vocab``
(:data:`VOCAB_SCHEMA`), the engine-owned display rank and severity class of every closed string vocabulary the
schema publishes (G43), so a glyph's level is the engine's and never a page mapping. ``vocab.ranked.<name>``
lists ``{token, rank, class}`` in rank order with the owner that fixed the order (``analyze._LIFECYCLE_BAND_RANK``,
``analyze._APP_SEV_RANK``, ``coverage_matrix.COVERAGE_STATE_ORDER``, ...; this module where no engine owner
ranks the vocabulary, as with :func:`_topology_legend`) and the basis of every class. ``vocab.unranked.<name>``
names every other closed vocabulary (evidence states, reasons, roles, names, presentation tokens) with why it
carries no level, so a vocabulary cannot be omitted silently: ``tests/test_ui_projection_vocab.py`` derives the
set of string enums from the schema itself and requires each to be classified exactly once. ``class`` is one of
:data:`VOCAB_CLASSES`: ``pass`` (the owner asserts a measured, acceptable condition), ``watch`` (a determined
condition that needs attention but does not gate), ``risk`` (a gating or elevated risk), ``critical`` (the
owner's most severe tier) and ``undetermined`` (the owner determines no level: absence, insufficiency, unknown,
unassessed or informational -- a glyph draws no level for it, never ``pass``). ``rank`` is the owner's display
order, 0 first; tokens the owner does not order apart share a rank.

A row cell never goes through a dotted path (a hostname can contain a dot): it takes its section's state,
the owner's device scope, its row join by exact key (two rows naming a key are ``unverified``, never picked
between), then its own not-observed rule and type check. Engine defaults that mean "not observed" (the
DevicePhysical ``""`` and ``0``, the ``[NOT OBSERVED]`` markers, sparse interface fields, empty routing
neighbour lists) are withheld, never published as values. A list the engine caps says so, and its total
is never computed. Per-device finding rollups use the engine's pure, unpersisted fold of stored punch-list
rows; unknown capture custody withholds every rollup, including a zero. Published finding evidence pointers, their basis and capped totals,
and the separate health deduction-reference subsequence retain the engine's values and ordering.

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

import ipaddress
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from cisco_toolkit import __version__ as _CODE_SCHEMA_VERSION
from cisco_toolkit import impact_assessability
from cisco_toolkit import ssot
from cisco_toolkit.analyze import (
    DOSSIER_AXIS_INPUTS, PUNCH_CATEGORIES, PUNCH_CATEGORY_SECTION, PUNCH_SEVERITIES, compute_device_findings,
    compute_punchlist_facets, device_config_capture, vlan_cutover_host_index,
)
from cisco_toolkit.coverage_matrix import (
    COVERAGE_DIMENSIONS, COVERAGE_STATE_ORDER, COVERAGE_VERDICT_SOURCES, CoverageRowIndex,
    compute_device_coverage, index_coverage_rows, match_coverage_cell,
)
from cisco_toolkit.protocol_assurance import BoundSnapshot, bound_snapshot_source

SCHEMA = "ui_projection/1"
SCHEMA_ID = "urn:atlas:schema:ui-projection:1"
TOPOLOGY_STYLE_SCHEMA = "ui_projection_topology_style/1"
TOPOLOGY_STYLE_TOKENS = (
    "observed", "uncollected", "unverified", "not_observed", ssot.ANALYSIS_UNAVAILABLE,
    "link_up", "link_down", "link_unknown", "structural_link", "structural_bridge",
    "impact_high", "impact_medium", "impact_low", "impact_info", "path_reached", "path_partial_drop",
    "path_observed_discard", "path_no_route_observed", "path_lower_bound", "path_withheld",
)
TOPOLOGY_GLYPHS = ("device", "router", "ap", "unknown", "none")
#: The legend's presentation dimensions (``_topology_legend`` owns the token -> tone/stroke/weight table).
TOPOLOGY_TONES = ("neutral", "muted", "info", "warning", "danger")
TOPOLOGY_STROKES = ("solid", "dashed", "dotted")
TOPOLOGY_WEIGHTS = ("normal", "strong")
#: The failure-impact owner's bands, worst first (analyze.compute_failure_impact sev_rank order).
IMPACT_SEVERITIES = impact_assessability.IMPACT_SEVERITIES
ADDRESS_ORIGINS = ("interface_svi", "local_route", "fhrp_host_route")
#: G17: the build.build_routing_neighbors row field that carries the neighbour's own address, per protocol key. OSPF's
#: 'neighbor' is the Neighbor ID column, a router ID that need not be any interface address, and its 'address' is the
#: adjacency address (parse.parse_ospf_neighbors); EIGRP and BGP name the peer by its address in 'neighbor'
#: (parse.parse_eigrp_neighbors, parse.parse_bgp_summary). tests/test_ui_projection_peer_host.py holds each entry to
#: the real parser's output and the keys to the producer's own protocol keys.
NEIGHBOR_ADDRESS_FIELDS: Mapping[str, str] = MappingProxyType({"ospf": "address", "eigrp": "neighbor",
                                                               "bgp": "neighbor"})
#: The FIB owner's route fields a hop may report invalid, and its MTU-gap reasons (fib.trace_fib_path).
FIB_ROUTE_FIELDS = ("admin_distance", "source", "next_hop", "out_intf")
FIB_MTU_GAP_REASONS = ("malformed_hop_evidence", "egress_interface_not_observed")

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
SEVERITIES: Tuple[str, ...] = PUNCH_SEVERITIES
#: The punch-list category vocabulary (analyze.PUNCH_CATEGORIES, the evidence-policy keys), in owner order.
FINDING_CATEGORIES: Tuple[str, ...] = PUNCH_CATEGORIES
#: The finding facets (G21), in payload order: two owner partitions of the rows, then the per-device rollup.
FINDING_FACETS: Tuple[str, ...] = ("severity", "category", "device")
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
#: G41: the one engine owner of a snapshot's source identity. Only protocol_assurance.bind_snapshot_json_bytes,
#: which parses and hashes ONE byte string, mints the process-local marker this owner reads back (and refuses once
#: the content changes). A parsed mapping alone names no file, and this module never hashes a re-serialisation.
SNAPSHOT_IDENTITY_OWNER = "protocol_assurance.bound_snapshot_source"
#: The owner's digest spelling (protocol_assurance.bind_snapshot_json_bytes): the algorithm, a colon, 64 lowercase hex.
SNAPSHOT_SHA256_PATTERN = "^sha256:[0-9a-f]{64}$"
#: The byte form of that digest: the exact byte string the reader parsed into this snapshot, with no newline or
#: encoding normalisation. A digest is only comparable with another of the same form (docs/ssot.md, the digest of
#: "one snapshot"). AssessHub parses its persisted store blob, so there it is the same byte string as the
#: transport's assesshub-store-blob identity; a file reader parses the file as read.
SNAPSHOT_DIGEST_FORM = "exact-parsed-bytes"
#: Lifecycle summary field -> band label (ssot lifecycle-band table), and its inverse.
LIFECYCLE_BAND_FACTS: Mapping[str, str] = MappingProxyType({
    "n_past_ldos": "Past-LDoS", "n_past_eos": "Past-EoS", "n_near": "Near-LDoS", "n_active": "Active",
    "n_unknown": "Unknown"})
LIFECYCLE_BAND_FACTS_BY_BAND: Mapping[str, str] = MappingProxyType(
    {band: name for name, band in LIFECYCLE_BAND_FACTS.items()})
#: The canonical lifecycle band order (analyze._LIFECYCLE_BAND_RANK), most severe first.
LIFECYCLE_BAND_ORDER: Tuple[str, ...] = ("Past-LDoS", "Near-LDoS", "Past-EoS", "Active", "Unknown")
#: The summary field names in canonical band order (the ``LifecycleBand.fact_name`` vocabulary).
LIFECYCLE_FACT_NAMES: Tuple[str, ...] = tuple(LIFECYCLE_BAND_FACTS_BY_BAND[b] for b in LIFECYCLE_BAND_ORDER)
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
#: G05 -- axis label -> where its producer stores how many devices the axis could NOT assess, and out of how many:
#: ``(producer, count path, denominator path, per-device rows path, row field, the field's could-not-assess value)``.
#: The brief publishes no per-axis denominator, so this table is owned HERE. Tests hold every entry against its
#: producer: the real producer writes the count equal to the number of its per-device rows carrying that value,
#: and the denominator equal to the number of those rows. The rows are the count's raw basis: a readable row list
#: that disagrees with the stored count or denominator makes both unverified.
AXIS_UNASSESSED: Mapping[str, Tuple[str, str, str, str, str, Union[str, bool]]] = MappingProxyType({
    "Hardware lifecycle (EoL)": ("analyze.compute_lifecycle_risk", "lifecycle_risk.summary.n_unknown",
                                 "lifecycle_risk.summary.n_devices", "lifecycle_risk.per_device", "band", "Unknown"),
    "Operational logs": ("analyze.compute_syslog_intelligence", "syslog_intelligence.summary.n_not_collected",
                         "syslog_intelligence.summary.n_devices", "syslog_intelligence.per_device", "collected", False),
    "QoS posture": ("analyze.compute_qos_audit", "qos_audit.summary.n_not_assessable", "qos_audit.summary.n_devices",
                    "qos_audit.per_device", "assessable", False),
    "Software risk": ("analyze.compute_software_risk", "software_risk.summary.n_config_not_assessable",
                      "software_risk.summary.n_devices", "software_risk.per_device", "config_assessable", False),
    "Platform capacity": ("analyze.compute_platform_health", "platform_health.summary.bands.Unknown",
                          "platform_health.summary.n_devices", "platform_health.per_device", "band", "Unknown"),
    "Asset risk register": ("analyze.compute_device_dossiers", "device_dossiers.summary.bands.Unassessed",
                            "device_dossiers.summary.n_devices", "device_dossiers.per_device", "risk_band",
                            "Unassessed"),
})
#: The counters whose producer omits an entry no device holds (a Counter): there, a missing could-not-assess entry is
#: a zero only when the per-device rows confirm that no device carries the value. Held by a test against the producer.
AXIS_UNASSESSED_SPARSE: FrozenSet[str] = frozenset({"platform_health.summary.bands",
                                                    "software_risk.summary.train_bands"})
#: Axis label -> the further layers its producer assesses beyond the layer its registered count covers: ``(path of the
#: producer's stored count of the devices that layer could NOT assess, the layer's name, its per-device rows path, the
#: row field, the field's could-not-assess value, the summary coverage key whose uncovered devices that count holds)``.
#: A layer's own could-not-assess count is read, never a coverage key standing in for it (W51: Software risk's
#: release-train layer is its train_bands Unknown count -- a release captured but not classified is not assessed --
#: never n_version_known). While that count is above zero (or cannot be read, or disagrees with its rows), the
#: registered count is not the axis's: it is withheld as not_collected, its value and the layer's gap named in the
#: reason. A test scans every registered producer's real summary for its per-layer coverage counts and holds each one to
#: this table (the layer's coverage key) or to the registered count it complements.
AXIS_UNASSESSED_LAYERS: Mapping[str, Tuple[Tuple[str, str, str, str, Union[str, bool], str], ...]] = MappingProxyType({
    "Software risk": (("software_risk.summary.train_bands.Unknown",
                       "release-train layer (a captured and classified software release train)",
                       "software_risk.per_device", "train_band", "Unknown", "n_version_known"),),
})
#: The axis whose count an owner computes live: ``ssot.fleet_avg_health``'s ``n_rows`` minus ``n_scored``, the brief's
#: own unscored health rows (the scored-row predicate the brief averages over), out of ``n_rows``.
AXIS_UNASSESSED_LIVE: Tuple[str, ...] = ("Fleet health",)
#: Axis label -> why its producer stores no count of devices it could not assess (both cells are not_collected).
AXIS_UNASSESSED_ABSENT: Mapping[str, str] = MappingProxyType({
    "Migration punch-list": "analyze.compute_migration_punchlist writes finding rows only, and keeps no record of "
                            "the devices it could not assess",
    "Application domains": "analyze.compute_application_intelligence summarizes application domains and their "
                           "couplings, not devices",
    "Cutover sequence": "its producers order application domains and give move-group readiness verdicts, not "
                        "per-device verdicts",
    "Segmentation": "analyze.compute_segmentation summarizes gateway interfaces and VRFs, not devices",
    "Multicast / timing": "analyze.compute_multicast_intelligence summarizes multicast groups, querier VLANs and PTP "
                          "clocks, not devices",
    "Remediation": "analyze.compute_remediation_plan counts the devices it generated configuration for, not the "
                   "devices it could not assess",
})
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
DOSSIER_INPUT_STATES: Tuple[str, ...] = tuple(ssot.ABSTENTION_STATES)  # analyze.compute_device_dossiers ax()
DOSSIER_EMPTY_IS_CLEAN: FrozenSet[str] = frozenset({"Config hygiene", "Physical"})  # analyze owner
DOSSIER_AXES: Tuple[str, ...] = ("Health", "Hardware EoL", "Software risk", "Control plane", "Operational logs",
                                "Security posture", "Config hygiene", "Golden drift", "QoS posture", "Physical",
                                "Protocol")  # analyze.DOSSIER_AXIS_INPUTS keys
STP_ROOT_ELECTION_STATES: Tuple[str, ...] = ("published", "ambiguous", "not_observed")  # stp_topology owner
STP_ROOT_ELECTION_REASONS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "published": ("single_claimant",),
    "ambiguous": ("malformed_root_rows", "multiple_root_identities", "duplicate_bridge_identity"),
    "not_observed": ("root_not_collected", "no_root_evidence"),
})
STP_ROOT_REASONS: Tuple[str, ...] = tuple(r for reasons in STP_ROOT_ELECTION_REASONS.values() for r in reasons)
STP_DEFAULT_BRIDGE_PRIORITY = 32768  # stp_topology._DEFAULT_BRIDGE_PRIORITY; validation only
VLAN_READINESS: Tuple[str, ...] = ("NOT READY", "CAUTION", "READY")     # analyze._VLAN_CUTOVER_READY_RANK
READINESS_CHECK_STATUSES: Tuple[str, ...] = ("pass", "warn", "fail", "info")  # analyze.compute_migration_readiness
# Snapshot sections supplied to compute_migration_readiness; dep_map and subject scopes are transient.
# These gate recorded failures, not the owner's intentional optional/direct-caller omission paths.
READINESS_INPUTS: Tuple[str, ...] = (
    "interfaces", "move_groups", "health_scores", "physical_health", "l3_forwarding", "cross_layer",
    "protocol_health", "protocol_assessability", "stp_roots", "bgp_configured_peer_baseline",
    "fhrp_configured_group_baseline", "fhrp_redundancy_domain_baseline", "vtp_safety_baseline",
    "ipv6_routing_adjacency_baseline")
ENDPOINT_CONFIDENCES: Tuple[str, ...] = ("Inferred-high", "Inferred-medium", "Unknown")    # analyze._EP_CONF
#: The statuses analyze.compute_collection_completeness lists (it lists only blind spots, never 'complete').
CC_STATUSES: Tuple[str, ...] = ("not collected", "partial")
SEC_STATUSES: Tuple[str, ...] = ("pass", "fail", "na")                          # parse.parse_security
SEC_SEVERITIES: Tuple[str, ...] = ("high", "medium", "low", "info")             # parse._SEC_CHECKS + "info"
SEC_GRADES: Tuple[str, ...] = ("weak", "partial", "hardened")                   # parse.parse_security
OP_STATUSES: Tuple[str, ...] = ("up", "down", "unknown")                        # analyze.compute_cable_map
NOT_OBSERVED_SENTINEL = "[NOT OBSERVED]"                                        # analyze.VLAN_CUTOVER_NOT_OBSERVED
AMBIGUOUS_STP_SENTINEL = "[AMBIGUOUS]"                                          # analyze.VLAN_CUTOVER_AMBIGUOUS
NRFU_NOT_OBSERVED = "[NOT OBSERVED — record baseline at execution]"        # nrfu_export.NOT_OBSERVED
PUNCH_BASIS_UNPUBLISHED = ("severity basis NOT published by this snapshot — check the finding's own "
                           "detail for what it rests on")                        # analyze.PUNCH_BASIS_UNPUBLISHED
PUNCH_CONFIDENCE_UNPUBLISHED = "evidence confidence NOT published by this snapshot"
# analyze.PUNCH_EVIDENCE_* owns these values. As with the other engine vocabularies above, this
# lightweight module imports only ssot; tests/test_ui_projection_evidence.py pins every copy to its owner.
PUNCH_EVIDENCE_BASES: Tuple[str, ...] = ("record", "row", "absence")
PUNCH_EVIDENCE_REF_KINDS: Tuple[str, ...] = ("interface", "acl_line", "route", "config_text",
                                          "device_fact", "analysis_row", "adjacency", "absence_witness")
PUNCH_EVIDENCE_RECORD_KINDS: FrozenSet[str] = frozenset({"interface", "acl_line", "route", "config_text"})
PUNCH_EVIDENCE_ROLES: Tuple[str, ...] = ("subject", "derived_from", "witness")
PUNCH_EVIDENCE_REFS_CAP = 64
PUNCH_EVIDENCE_RULES: Mapping[str, bool] = MappingProxyType({
    "total_only_when_capped": True,
    "absence_forbids_record_kinds": True,
    "record_requires_record_kind": True,
    "row_requires_ref": True,
    "host_must_be_row_device_or_null": True,
})
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
    "health_scores[].deduction_refs": 8,                  # same prefix, with unaddressable refs omitted
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
    # analyze.compute_failure_impact simulates over build_network_model: access-VLAN membership from the switchport
    # parse and inter-switch links from CDP/LLDP (compute_topology_links). It reads no interface-status or
    # version/inventory field; its MAC, trunk and STP inputs are not essential captures. Its gateways are SVIs with
    # an IP, which build.py takes only from the scoped interface running-config capture (svi_ip), marking each
    # interface it parsed run_config_observed. The shared row builder applies that per row (the engine owner's
    # impact_assessability.row_hold), so the fleet row and the device page hold the same values; the full
    # running-config (the security row) is not it.
    "failure_impact": ("switchport", "CDP/LLDP neighbors"),
    # analyze.compute_link_centrality: CDP/LLDP links between two scanned hosts (_topology_adjacency).
    "structural_links": ("CDP/LLDP neighbors",),
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
    "stp_root_state": ("stp_roots",), "stp_root_reason": ("stp_roots",),
    "stp_root_claimants": ("stp_roots",), "stp_root_identities": ("stp_roots",),
    "gateway_svi_hosts": ("interfaces",), "endpoint_count": ("endpoint_identity",),
    "endpoint_mix": ("endpoint_identity",), "app_domain": ("application_intelligence",),
    "criticality": ("application_intelligence",), "dependencies": ("multicast_intelligence", "interfaces"),
    "wave": ("move_groups", "wave_sequencing", "interfaces", "stp_roots"),
    "scenario": ("move_groups", "wave_sequencing"),
    "readiness": ("move_groups", "migration_readiness"), "cutover_window": (), "rollback_owner": (),
})
#: The ``compute_migration_punchlist`` inputs that are snapshot sections (its rows roll up over them).
PUNCHLIST_INPUTS: Tuple[str, ...] = (
    "cross_layer", "security", "config_hygiene", "physical_health", "l3_forwarding", "protocol_health",
    "health_scores", "move_groups", "syslog_intelligence", "qos_audit", "software_risk", "platform_health",
    "device_dossiers", "protocol_assessability", "vtp_safety_baseline", "ipv6_routing_adjacency_baseline")
#: The snapshot-local identity written by ``compute_move_groups``; legacy rows may lack it.
MOVE_GROUP_LABEL = "group"
MOVE_GROUP_UNSCHEDULED = "(unscheduled)"  # analyze.MOVE_GROUP_UNSCHEDULED


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
         "/overview/fleet_health/bands", "/overview/readiness/groups",
         "/inventory/devices", "/inventory/vlans", "/inventory/endpoints", "/inventory/uncollected_peers",
         "/findings/rows", "/findings/total", "/findings/facets", "/findings/cross_layer", "/topology",
         "/trust/inputs"]),
    _limitation(
        "axis_basis_owned_by_projection",
        "cisco_toolkit.ui_projection.AXIS_BASIS, cisco_toolkit.ui_projection.AXIS_UNASSESSED",
        "analyze.compute_executive_brief publishes no per-axis basis. The axis-to-input table is owned by "
        "this projection and held against the producer's source by tests; an unregistered axis label fails "
        "closed to every brief input. The producer omits an axis whose input carries nothing to report; "
        "absent_axes names every registered axis the brief does not carry. Nor does the brief publish how many "
        "devices an axis could not assess: each axis's unassessed n, out of of, is read from that axis's producer "
        "through a table this projection owns (AXIS_UNASSESSED), held against the producers by tests, never from "
        "the headline text. Hardware lifecycle counts the devices with no authoritative lifecycle band; Operational "
        "logs, the devices whose log buffer was not collected (a captured buffer counts as assessed even when no "
        "line in it was recognised: its producer stores no count of those); QoS posture, the devices with no full "
        "running-config; Software risk, the devices with no running-config, which is only its configuration layer; "
        "Platform capacity, its Unknown band (capacity output absent or unrecognised; that counter omits a band no "
        "device holds, so a zero is published only when the per-device rows confirm it); Asset risk register, its "
        "Unassessed band; Fleet health, ssot.fleet_avg_health's health rows minus its scored rows. Each is out of "
        "that producer's own device count, so the counts cover different device universes and are never added "
        "across axes; none of those universes holds an inventory device the collection never reached "
        "(fleet_lists_exclude_blind_devices). A count that covers one layer of an axis whose producer assesses "
        "another (AXIS_UNASSESSED_LAYERS: Software risk's release-train layer, read from that layer's own count of the "
        "devices it could not assess, train_bands Unknown -- a release captured but not classified is not assessed -- "
        "never from n_version_known) is that axis's count only while that layer's count is zero; otherwise it is "
        "withheld as not_collected, its value and the other layer's gap named in the reason, with a witness ref to "
        "that layer's count. A device a dossier axis marked na is not counted. A count is unverified when it, or a "
        "further layer's count, exceeds its denominator, or when its producer's per-device rows disagree with it "
        "or cannot be read; these checks are this projection's. A count follows its row: when a failed phase makes "
        "the row's fact analysis_unavailable (the brief itself, or any input the row's basis names, which for an "
        "unregistered label is every brief input), both cells are analysis_unavailable with the same failure "
        "records. An axis whose producer stores no such count is not_collected, never 0.",
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
        ["/overview/facts", "/overview/axes", "/overview/lifecycle", "/trust/unknown_evidence",
         "/trust/ssot/engine_stamp", "/inventory/devices/total", "/trust/inputs"]),
    _limitation(
        "abstention_addresses_dict_paths_only", "ssot.abstention_reason",
        "The abstention core cannot address an array element. A list item takes its list's state, then its "
        "basis sections' failure or blind-spot state, then its own type check. It reads dotted paths, so it cannot "
        "address a path through a hostname that contains a dot either: a row cell takes its section's state and "
        "the device scope of ssot.abstention_reason, then its own row join and type check.",
        ["/overview/axes", "/overview/top_gating", "/trust/failures/record", "/trust/unknown_evidence/sources",
         "/inventory/devices", "/inventory/vlans", "/inventory/endpoints", "/findings/rows", "/findings/cross_layer"]),
    _limitation(
        "coverage_matrix_shown_as_published", "coverage_matrix.compute_coverage_matrix",
        "The coverage matrix is shown exactly as the engine published it and is never recomputed. The "
        "engine emits 'covered' where a coverage source (capture_integrity, parse_yield) is silent, so a "
        "covered row is not proof that those sources ran, and a zero count from it is withheld as "
        "unverified.",
        ["/trust/coverage_matrix", "/inventory/devices/rows"]),
    _limitation(
        "projection_owned_verdicts", "cisco_toolkit.ui_projection",
        "These verdicts are this projection's, not an engine owner's: census matches_live (rows compared by "
        "key), stamp_matches_live, snapshot_schema_supported, the top_gating check against the producer's "
        "rule (every Critical/High axis headline, in axis order) and its axis_index join, the always-emitted "
        "axis check, and the unverified state for a failed type check, an integer above 2^53-1, a reconcile "
        "violation or an owner fault. On the row screens: the device total's row-count check, the punch-list "
        "priority and rank checks against the producer's rule, a cap's reached flag, the incomplete state of a list "
        "whose input a blind spot, a missing essential capture or a missing security row withheld, the unverified "
        "state of a key join or device scope that a row it cannot read, or a second row naming the key, leaves "
        "open, the empty "
        "VLAN-dependency and default-election checks against the gateway SVI and root-bridge records, the "
        "completeness claim of the uncollected-peer list, and the finding facets' partition check (a severity or "
        "category facet is published only when the owner's buckets place every stored row exactly once, each in "
        "the bucket its own field names, in agreement with the row list and its published total; while that total "
        "is not published no severity or category count is) and their source-section check against "
        "analyze.PUNCH_CATEGORY_SECTION, and the cross-layer checks against their producers: a host a row names twice "
        "or names blank, a host with no devices-map record or no health row, a row naming no host, and a deduction "
        "reference or line item that is missing, repeated or foreign.",
        ["/trust/census/embedded/matches_live", "/trust/ssot/stamp_matches_live",
         "/engine/snapshot_schema_supported", "/overview/top_gating", "/overview/absent_axes",
         "/inventory/devices/total", "/inventory/vlans", "/inventory/endpoints", "/inventory/uncollected_peers",
         "/findings/rows", "/findings/facets", "/findings/cross_layer"]),
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
        "'at least this many'; the projection never computes the missing total. Finding evidence references are "
        "capped separately at the engine's evidence cap; only their producer-published evidence_refs_total can "
        "state the uncapped count. Health reference truncation follows the deduction prefix before missing refs "
        "are removed, so its shorter subsequence may also be capped. A cross-layer row whose device's published "
        "deductions reached that cut, and carry no reference to the row, may drive a deduction beyond it: that "
        "deduction is withheld as not collected, never shown as absent.",
        ["/inventory/vlans", "/inventory/endpoints/dual_homed", "/findings/rows", "/findings/cross_layer"]),
    _limitation(
        "move_group_label_absent", "analyze.compute_move_groups",
        "Legacy move-group rows have no stored 'group' labels. This projection does not invent positional labels "
        "or use partially labelled, duplicate or malformed groups to assert a device's identity. Values depending "
        "on those labels are withheld; current snapshots retain the labels their producer writes.",
        ["/findings/rows", "/inventory/endpoints/dual_homed", "/inventory/devices", "/overview/readiness/groups"]),
    _limitation(
        "move_group_endpoints_not_distinct", "analyze.compute_move_groups",
        "Endpoints is the sum of per-switch distinct learned MAC addresses on eligible access ports, not "
        "distinct endpoints across a move group; one MAC observed on multiple switches can be counted more "
        "than once. This is a blast-radius proxy.",
        ["/overview/readiness/groups"]),
    _limitation(
        "migration_readiness_check_scope", "analyze.compute_migration_readiness",
        "Readiness follows the published checks: fail means NOT READY, warn means CAUTION, and pass/info "
        "alone mean READY. An info check can state that evidence was not assessable or a manual action remains; "
        "its note is preserved and READY does not turn that abstention into verified coverage. An IPv6 adjacency "
        "note names at most eight blocker subjects, then discloses the exact omitted count and their authoritative "
        "Cutover Validation/NRFU records; it does not present the named subjects as the complete blocker list.",
        ["/overview/readiness/groups"]),
    _limitation(
        "health_band_partition_rows_only", "ssot.health_band_partition",
        "Band counts and membership partition the published health records, not every inventory or blind "
        "device. An omitted health record contributes no member and is not proof that its device is healthy. "
        "Insufficient Data retains its observed membership while measured-band facts abstain over an unscored fleet.",
        ["/overview/fleet_health/bands"]),
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
        "vlan_readiness_scope", "analyze.compute_vlan_cutover_matrix",
        "VLAN readiness is the producer's join of move-group migration-readiness verdicts; it does not establish "
        "STP root ownership. Consult the row's STP election state and reason: ambiguity, unobserved roots and "
        "missing legacy verdicts remain unresolved even when readiness is READY. Malformed or duplicate owner verdicts "
        "withhold READY rather than replacing it with another verdict.",
        ["/inventory/vlans/rows"]),
    _limitation(
        "vlan_gateway_rows", "excel.write_l3_forwarding_sheet; cisco_toolkit.ui_projection",
        "A VLAN row's selections.gateways lists the stored l3_forwarding rows that name its VLAN id: one per scanned "
        "device SVI named VlanN with an address, an FHRP group or a connected route. The producer counts no other "
        "interface (a routed port, subinterface, BDI, BVI or irb unit) as a VLAN's gateway. host, svi_ip and role are "
        "that row's switch, SVI address and FHRP role as captured, a point-in-time state; an empty address or role is "
        "withheld, never read as 'no FHRP'. tracking is the device's 'show track' summary, not bound to this SVI or its "
        "FHRP group (the HSRP detail's per-group track list, fhrp_detail[].track, is not projected here); it states the "
        "full object count, then the state of at most 6 objects. The producer's not-observed marker is withheld as not "
        "collected, never 'no tracking', and a text that disagrees with the row's tracked-object-down flag is "
        "unverified. An empty tracking text means a captured 'show track' with no tracked object only where the "
        "snapshot proves its producer separates the two (a not-observed tracking or risk marker, or an interface "
        "marked run_config_observed); otherwise it is withheld. risk is the sole-gateway risk alone: the producer's "
        "single-gateway flag, never its no-FHRP or tracked-object-down flags. The producer counts gateways by VLAN id "
        "across the scan, so false is published only where another switch's gateway row provably shares this "
        "gateway's segment: the same primary subnet and SVI network, in the same VRF where both can be read, and "
        "positive evidence that the two switches share one layer-2 domain for the VLAN -- a stored cable path every "
        "hop of which joins two collected ports trunking the VLAN, or the same spanning-tree root bridge for the VLAN "
        "on both. A matching subnet, FHRP group or virtual address alone is not that evidence (cloned sites reuse "
        "them). It says the scan saw another gateway for the segment, not that the gateway is healthy. These verdicts are this "
        "projection's: true is published only where the scan covers every gateway the producer's VlanN rule could "
        "count and no stored record contradicts it. That needs no collection blind spot, no cable-map neighbour the "
        "collection never reached that could route, every collected device's interface running-config captured, no "
        "other collected interface holding an address in the gateway's subnet, and no stored FHRP evidence of another "
        "router in its group (its own role, or the HSRP detail's standby router or state). The fleet-wide parts are "
        "fleet-wide because VLAN carriage per cable is not stored. A gateway that neither the collection nor CDP/LLDP "
        "discovered, and that no stored FHRP record names, is outside every scan. A flag that contradicts the stored "
        "rows' gateway count is unverified. The row's fhrp text naming a sole gateway is published only where that "
        "gateway's sole-gateway risk is published true. A published gateway list under a coverage gap may be "
        "incomplete and cites the gap, at most 8 witnesses per gap with the full count in its reason; an empty one is "
        "then not a clean result.",
        ["/inventory/vlans/rows"]),
    _limitation(
        "punch_rows_carry_no_evidence_pointers", "analyze.compute_migration_punchlist",
        "A legacy punch-list row has neither evidence_refs nor evidence_basis. That snapshot publishes no "
        "per-finding evidence pointers; a show command alone does not locate a supporting record.",
        ["/findings/rows", "/findings/total"]),
    _limitation(
        "row_selection_by_exact_key", "cisco_toolkit.ui_projection",
        "Rows are joined to a device, VLAN or endpoint by exact key equality, with the owner's own key rule; a "
        "collection_completeness blind-spot row is joined by the rule of its owner's device scope (the name without "
        "case or surrounding space, ssot.abstention_reason). Two rows naming the same key are unverified, never "
        "picked between. A row the join cannot read (not an object, or a key that is missing or not text) could "
        "name any key, so while a list holds one, every row joined or selected from it by device is unverified, "
        "with a witness to each such row: a row neither attaches to a device silently nor vanishes from it. The "
        "device scope is held to the same rule: while collection_completeness holds a row it cannot join, a second "
        "row naming a device, or a row whose status its owner's vocabulary does not name, or carries its devices as "
        "something other than a list (or itself as something other than an object, which its owner reads as listing "
        "no blind spot), a value about a device the scope does not call not collected is unverified, with a witness "
        "to each such row or value. The inventory is the union of the devices map and the collection_completeness "
        "blind spots; a blind-spot row it cannot join by host, or a blind-spot list it cannot read, makes the "
        "inventory rows and their reconciled count unverified, with a witness to that row or value. A host no "
        "readable roster names is unverified, with a witness to each roster row or roster it cannot read, while any "
        "is present. "
        "Pointer-only selections are null when their source could not be read (selection_sources says why), and [] "
        "when it was read and names nothing. STP observation selections instead carry their own FactList state and "
        "original record pointers. Their flags are stored parser output, not a new election: even False beside a "
        "parsed root address does not independently prove a non-root device or complete capture, because the parser "
        "does not retain bridge_address. An empty selection establishes neither root absence nor collection success. "
        "A VLAN row's selections.gateways is a fact list instead: it carries its own "
        "state and reason, and a row of its source the join cannot read makes it unverified. A cross-layer row's "
        "host joins the devices-map record and the health_scores row of exactly that name. The deduction the row "
        "drives on that device is the one deduction reference the health row publishes to the cross-layer row, and "
        "its line item is the published deduction carrying the row's own rule id and severity label "
        "(analyze.compute_health_scores writes '<id> <severity> (-<points>)'), never paired with a reference by "
        "position. Several identical line items on one device are one published value with a witness to each and no "
        "subject. The points are the scorer's per-item weight as published, before its per-category cap and the "
        "device's criticality factor, so they are not the change in the score.",
        ["/inventory/devices", "/inventory/endpoints", "/inventory/vlans", "/findings/cross_layer"]),
    _limitation(
        "fleet_lists_exclude_blind_devices", "analyze.compute_collection_completeness",
        "collection_completeness lists devices the collection reached only partly or not at all. A fleet list derived "
        "from device evidence holds only what was collected: an uncollected capture adds no row, and a failure-impact "
        "or structural-link row is computed over the scanned model without it, so even a 'no impact' row or a small "
        "pairs-cut count was never checked against that evidence. Cross-layer correlations are computed over the same "
        "collected evidence, so an uncollected device can neither add nor clear one. While any blind spot is listed, "
        "a published list carries this caveat, with a witness ref to each blind-spot row, and an empty one is "
        "not_collected, never 'nothing found'. The owner lists only blind spots, so a row that cannot be read as one "
        "(not an object, or a status outside its vocabulary) qualifies the list the same way, with a witness ref to "
        "that row, and so does a blind-spot list carried as something other than a list (or its section as something "
        "other than an object), which its owner reads as listing none, with a witness ref to that value. The record "
        "is never trusted by default: one that the snapshot does not carry, whose phase failed (with a ref to its "
        "failure record, never dropped by a witness cap), or whose summary counts a partial or not-collected device "
        "its list does not carry, cannot be read, or counts an inventory other than the inventory rows' count, "
        "qualifies the list the same way. A finding facet count follows the same rule: a positive severity or "
        "category count is a lower bound that carries this caveat, and a zero is not_collected. An executive axis's "
        "count of the devices it could not assess, and its denominator, are likewise taken over its producer's own "
        "devices, which hold only the devices whose evidence that producer was given: a device the collection never "
        "reached is in neither. While any blind spot is listed, each published count and denominator carries this "
        "caveat with the same witness refs, and a zero count, a count over no device, or an empty denominator is "
        "not_collected, never 'none left unassessed'.",
        ["/overview/axes", "/inventory/vlans", "/inventory/endpoints", "/findings/rows", "/findings/total",
         "/findings/facets", "/findings/cross_layer", "/topology/structural_links", "/topology/failure_impact"]),
    _limitation(
        "findings_without_running_config", "analyze.compute_migration_punchlist",
        "A device in the devices map with no security row (no captured running-config) contributes no "
        "configuration-derived punch-list row (security, configuration hygiene, QoS). While any device lacks one, "
        "published findings carry this caveat, with a witness ref to each such device record, and an empty list is "
        "not_collected. A positive severity or category facet count is then a lower bound that carries this caveat, "
        "and a zero facet count is not_collected.",
        ["/findings/rows", "/findings/total", "/findings/facets"]),
)
LIMITATIONS += (
    _limitation("device_findings_scope", "analyze.compute_device_findings",
                "Counts cover stored punch-list rows once per named device. A multi-device row contributes "
                "to each named device, so device totals are not distinct fleet findings. An assessed-empty "
                "count is not a clean bill of health; capture custody and input qualification remain visible. "
                "The device finding facet is this rollup summed for each inventory device (the devices map and "
                "the collection_completeness blind spots), so a row naming no inventory device counts under no "
                "device key and a multi-device row under each device it names, so the device counts need not sum "
                "to the row total.",
                ["/inventory/devices/rows", "/findings/facets/device"]),
    _limitation("topology_scanned_model", "analyze.compute_cable_map; analyze.compute_link_centrality",
                "The graph describes captured discovery and the scanned host-pair model. A collected node is not "
                "a health verdict; an up cable is a reported link state, not end-to-end reachability. Structural "
                "metrics describe host pairs, not individual cable redundancy, and the owner writes one record per "
                "unordered host pair: two rows naming one pair, in either orientation, are each kept and unverified "
                "with a witness to every such row, never picked between. Uncollected peers and ambiguous endpoint "
                "joins remain visible; absent links are not proof of disconnection. A cable-map node or cable row an "
                "exact hostname or host-pair join cannot read (not an object, or a host that is missing or not text) "
                "could carry that name or pair, so beside one the join is unverified, with a witness to each such "
                "row: never a single node or cable picked, and never 'none'.", ["/topology"]),
    _limitation("impact_scanned_scope", "analyze.compute_failure_impact",
                "Impact is limited to the scanned VLAN/carriage model. Stranded endpoints exclude those on the "
                "removed host itself. Info and zero are not an assessed/healthy result; retain the owner's "
                "indeterminate coverage detail. A row's severity and counts are withheld, not shown as "
                "measurements, where the owner could not simulate the switch (its INDETERMINATE detail, or a "
                "positive off_scan_gw_vlans with no VLAN simulated), where the stored row carries no "
                "off_scan_gw_vlans (it predates that marker), or where no interface of the switch carries "
                "run_config_observed (its gateway SVIs come only from that capture). A row that simulated some VLANs "
                "and has a positive off_scan_gw_vlans covers only its VLANs with an in-scan gateway: a severity "
                "below High is withheld because it may understate, a zero count is withheld because a lower bound "
                "of zero is not a measurement of none, and High and positive counts are published as lower bounds "
                "that cite that count. A withheld row's detail is withheld with its measures unless it is the "
                "owner's INDETERMINATE disclosure; a partial row's per-VLAN detail stays published as the list of "
                "what was simulated. A row's blind_links (cited, not shown as a cell) counts the switch's "
                "inter-switch links with no trunk/STP evidence on either end; the owner leaves them out of every "
                "forwarding graph, so a VLAN the switch transits only over one was never simulated. A positive "
                "blind_links bounds the row as a positive off_scan_gw_vlans does and also withholds a detail that "
                "names no simulated VLAN; with no VLAN simulated, it withholds the row's measures. A stored row "
                "without blind_links predates that count (the owner then disclosed such links at most for a switch "
                "it simulated nothing for), so it is bounded the same way, citing the row. Such a link can also hide "
                "an alternate path, so a removal elsewhere may read worse than it is: a published High or positive "
                "count is a lower bound against its own row's blind_links, not against other rows'. A switch the "
                "stored cable map cables to a peer it does not show as collected "
                "(collected: false and a kind other than ap, phone or endpoint, or a cable end that joins no single "
                "node, which every cable end is while a node row cannot be joined by host) cannot account for "
                "endpoints behind that peer: a severity below High, a zero count and a "
                "detail that names no simulated VLAN are withheld, and High and positive counts are published as "
                "lower bounds that cite each such cable. Where the stored cable list cannot be read (absent, "
                "malformed or from a failed phase), whether a switch faces such a peer cannot be checked, so its row "
                "is bounded the same way and cites that list, or the nearest record it is missing from: the cable "
                "map, or the snapshot root when there is no cable map. The owner writes one row per host: two rows "
                "naming one exact host are each kept and unverified, with a witness to every such row, never picked "
                "between, "
                "and a hold or bound that also applies is carried beside that doubt. Detail lists up to 8 per-VLAN "
                "examples and preserves the owner's '+N more' disclosure; the row counts retain the full model totals.",
                ["/topology/failure_impact"]),
    _limitation("path_route_model_only", "fib.trace_fib_path",
                "This is an offline route-model query, not live traffic proof. It does not model VRF selection, "
                "ports, ACLs, NAT, stateful policy or reverse paths. Source suggestions are observed addresses, "
                "not management suitability or unique source ownership. A scoped no-route observation is not "
                "an observed discard. Reached paths can still have dropping ECMP legs. MTU evidence is "
                "IPv4-specific and does not establish IPv6 suitability.", ["/topology/source_addresses"]),
    _limitation("finding_facet_source_incomplete", "analyze.PUNCH_CATEGORY_SECTION",
                "The engine folds each punch-list category from one source section (analyze.PUNCH_CATEGORY_SECTION), "
                "which is not always a punch-list input. While a category's section was not collected, its phase "
                "failed, a failure the run recorded cannot be attributed to sections (an intermediate phase or a "
                "label nobody classified, which could have fed any of them), the section is stored as a container "
                "other than its producer's, or the abstention core could not read it, that category's count cannot be "
                "complete: a "
                "positive count is a lower bound that carries this caveat, with a ref to the section or its failure "
                "record, and a zero is not_collected, analysis_unavailable or unverified, never a clean result. A row "
                "of any category can carry any severity, so while any category's section is incomplete every "
                "severity count follows the same rule.",
                ["/findings/facets/severity", "/findings/facets/category"]),
)
LIMITATIONS += (
    _limitation("trust_inputs_scope",
                "analyze.compute_device_dossiers, analyze.compute_collection_completeness, cisco_toolkit.ui_projection",
                "The analysis inputs are the engine's per-device risk-register axes and their input sections "
                "(analyze.DOSSIER_AXIS_INPUTS), not every analysis: a fleet or findings-only section (for example "
                "cross_layer or l3_forwarding) writes no per-device custody, so no device is counted here, as a gap "
                "or as clean, from its absence. A device counts as not assessed by an input where its dossier row "
                "marks that axis 'na'; the device's custody keeps the engine's input state (not collected, analysis "
                "unavailable, or collected but empty: evidence was read but nothing assessable, such as no "
                "authoritative lifecycle band). A collection_completeness 'not collected' device is listed under "
                "every input whatever its dossier says. An assessed axis is the engine's bounded conclusion, not proof "
                "that every sub-input ran: Protocol concludes when at least one protocol family is assessable, and "
                "Config hygiene and Physical read an empty screen as clean. Dossier rows are joined by exact host and "
                "blind spots by their owner's device scope; a missing, duplicated or malformed row makes the count "
                "unverified, and the denominator is the inventory count the device rows reconcile to. The fold is "
                "this projection's; nothing is recomputed from raw evidence.",
                ["/trust/inputs"]),
)
#: What a device document cannot claim; addressed inside a ``DeviceDocument``.
DEVICE_LIMITATIONS: Tuple[Mapping[str, Any], ...] = (
    _limitation(
        "deduction_refs_are_subsequence", "analyze.compute_health_scores",
        "deduction_refs preserves an ordered subsequence of the published deductions. A deduction whose source "
        "has no addressable record contributes no ref. References retain their own citation and pointer and must "
        "never be paired with deduction text by index. Both lists are cut after the same first eight deductions, "
        "so even fewer than eight references can omit later deductions; no uncapped total is published.",
        ["/device/health/deduction_refs", "/device/health/deduction_refs_cap"]),
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
    _limitation(
        "routing_peer_resolution_scope", "fib._connected_index, fib._hosts_owning_ip, build.build_routing_neighbors",
        "peer_host is an exact address match, not an adjacency or reachability proof. It names the one collected "
        "device that the address index (topology.source_addresses) places the neighbour's address on: configured "
        "IPv4 interface addresses, primary and secondary, from the scoped interface running-config, plus in-scope "
        "local and FHRP host routes. OSPF resolves its adjacency address, never its router ID. VRF selection is not "
        "modelled: the index spans every VRF a captured interface configures, so an address on two devices in any "
        "VRFs is unverified, and a published owner may carry the address in another VRF than the adjacency, where an "
        "uncollected device could reuse it. Both a published owner and 'not resolved' (collected_but_empty) are "
        "stated only over a readable, complete index: every input collected, every collected device's interface "
        "addresses captured, and a readable collection_completeness record, which completes the device roster with "
        "the inventory devices never reached. Otherwise a device the index cannot hold could be a second owner, so a "
        "sole observed owner is not_collected, like an absence, and the reason states how many coverage gaps there "
        "are (a capped number of them are cited). 'Not resolved' means that no record in the index states the "
        "address. An address neither source states is not observed: a DHCP or negotiated interface address whose "
        "local route was not captured in scope, or a firewall's failover standby address. Every IPv6 address is "
        "not_collected, because the interface addresses the index takes from the running-config are IPv4 only.",
        ["/device/routing_neighbors"]),
)
#: The payload limitations a device page can cite, re-addressed into a ``DeviceDocument`` (so the document defines
#: every caveat it carries): limitation id -> its applies_to inside the document.
DEVICE_CITED_LIMITATIONS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "one_hop_failure_attribution": ("/device/collection", "/device/health", "/device/lifecycle", "/device/dossier",
                                    "/device/coverage", "/device/links", "/device/remediation", "/device/nrfu_cases",
                                    "/device/findings", "/device/endpoints", "/device/move_group", "/device/findings_rollup",
                                    "/device/coverage_rollup", "/device/failure_impact", "/device/structural_links"),
    "device_findings_scope": ("/device/findings_rollup",),
    "coverage_matrix_shown_as_published": ("/device/coverage", "/device/coverage_rollup"),
    "projection_owned_verdicts": ("/device/health/deductions_cap", "/device/remediation/items", "/device/links",
                                  "/device/native_vlan_mismatches", "/device/findings", "/device/endpoints",
                                  "/device/failure_impact", "/device/structural_links"),
    "device_physical_defaults_not_observed": ("/device/physical",),
    "health_scored_without_security": ("/device/health",),
    "health_scored_over_partial_collection": ("/device/health",),
    "dossier_band_over_unassessed_axes": ("/device/dossier/risk_band",),
    "engine_list_capped": ("/device/health/deductions", "/device/health/deduction_refs", "/device/remediation/items"),
    "move_group_label_absent": ("/device/remediation/items", "/device/move_group"),
    "row_selection_by_exact_key": ("/device/links", "/device/native_vlan_mismatches", "/device/findings",
                                   "/device/endpoints", "/device/failure_impact", "/device/structural_links"),
    "topology_scanned_model": ("/device/failure_impact", "/device/structural_links"),
    "impact_scanned_scope": ("/device/failure_impact",),
    "fleet_lists_exclude_blind_devices": ("/device/failure_impact", "/device/structural_links"),
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
    "nonnegative_number": "a finite nonnegative number within the browser's exact integer range",
    "positive_count": "a positive integer within the browser's exact integer range",
    "structural_ends": "an {a_host, a_port, b_host, b_port} text record",
    "count": "a non-negative integer no larger than 2^53-1, the largest integer a browser keeps exact",
    "score": "a finite number from 0 to 100",
    "text": "a string", "flag": "a boolean", "enum": "a value of its closed vocabulary",
    "axis": "a {severity, headline, detail} record with a known severity",
    "by_state": "a mapping of coverage states to counts",
    "severity_counts": "a closed mapping of every punch-list severity to exact nonnegative integer counts",
    "stamp": "a {verified, n_facts, n_checked, n_violations} record",
    "source": "a {section, state, records_examined, detail_complete} record",
    "list": "a list",
    "text_list": "a list of strings",
    "fhrp": "an FHRP record {proto, group, vip, members} or the engine's text",
    "exposure": "an {axis, state, label, input_state} record with known and consistent risk/input states",
    "stp_identities": "a list of closed STP identities with exact signed browser-safe integer priorities",
    "compound": "a {code, title, severity, basis} record with a known severity",
    "security_check": "an {id, title, severity, status, detail, cis_ref, remediation} record with a known severity "
                      "and status",
    "security_summary": "a {fail, pass, na, grade} record with a known grade",
    "trunk_native": "an {a_host, a_port, a_native, b_host, b_port, b_native} record of strings",
    "cable_ends": "an {a, a_port, b, b_port, is_pc} record",
    "coverage_cell": "a coverage state of its closed vocabulary",
    "shared_ip": "an {ip, switches, macs} record",
    "evidence_ref": "a closed {kind, host, ref, role, cite} record using the engine's evidence vocabulary",
    "sha256": "a 'sha256:' digest of 64 lowercase hexadecimal digits",
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
_R_UNJOINABLE_STEM = ("unverified: {n} row(s) in {section} cannot be joined by exact key (not an object, or a key "
                      "field that is missing or not text), and any of them could name ")
_R_UNJOINABLE = _R_UNJOINABLE_STEM + "this device"
#: The blind-spot list the owner's device scope reads (ssot._device_not_collected).
_CC_ROWS: Tuple[str, str] = ("collection_completeness", "devices")
#: Why the owner's device scope cannot be trusted to say a device is NOT a blind spot (:meth:`_Ctx.scope_doubt`).
_R_SCOPE = ("unverified: whether collection_completeness lists this device as partial or not collected cannot be "
            "read: {parts}")
_R_SCOPE_UNJOINABLE = ("{n} collection_completeness row(s) cannot be joined by host (not an object, or a host that is "
                       "missing or not text), and any of them could be this device's")
_R_SCOPE_AMBIG = ("{n} collection_completeness rows name this device (without case or surrounding space), but the "
                  "owner's device scope (ssot.abstention_reason) reads only the first of them")
_R_SCOPE_STATUS = ("the collection_completeness row naming this device states no status its owner's vocabulary names "
                   "({statuses}), and the owner's device scope reads any other status as collected")
_R_SCOPE_LIST = ("{path} is present but is not {kind}, and the owner's device scope (ssot.abstention_reason) reads it "
                 "as listing no blind spot, so any device could be one")
_R_INVENTORY_UNJOINABLE = ("unverified: {n} collection_completeness row(s) cannot be joined by host (not an object, or "
                           "a host that is missing or not text), so a blind-spot device they list may be missing from "
                           "these rows")
_R_INVENTORY_UNREADABLE = ("unverified: {path} is present but is not {kind}, so the blind-spot devices it lists cannot "
                           "be read and may be missing from these rows")
_R_UNKNOWN_HOST_DOUBT = ("unverified: no readable roster in this snapshot names this device (devices, "
                         "collection_completeness, cable_map), but {parts}")
_R_ROSTER_UNJOINABLE = ("{n} roster row(s) cannot be joined by host (not an object, or a host that is missing or not "
                        "text), and any of them could name it")
_R_ROSTER_UNREADABLE = ("{path} is present but is not {kind}, so no name it holds can be read, and it could name this "
                        "device")
#: A host-pair join over cable_map.cables (a structural link's candidate cables) that a row it cannot read leaves open.
_R_PAIR_UNJOINABLE = ("unverified: {n} row(s) in cable_map.cables cannot be joined by exact host pair (not an object, "
                      "or an end that is missing or not text), and any of them could cable this host pair")
_R_PAIR_AMBIG = ("unverified: {n} rows in link_centrality name this unordered host pair (in either orientation), but "
                 "analyze.compute_link_centrality writes one record per pair, so no single row can be chosen")
_R_NOT_SCORED = ("not assessed: the engine banded this device 'Insufficient Data' (a collection gap or an interface "
                 "set it could not parse), so its score is not a measurement (analyze.compute_health_scores)")
_R_MG = ("not collected: the legacy snapshot's move groups carry no 'group' label (analyze.compute_move_groups), so this value "
         "has no verifiable stored group identity")
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
# G41 (snapshot identity in the engine block).
_R_SOURCE_UNBOUND = ("not collected: this projection received a parsed snapshot without the exact bytes it was read "
                     "from, so it names no file. Only the reader that holds those bytes can bind them "
                     "(protocol_assurance.bind_snapshot_json_bytes); a hash of a re-serialisation would name a "
                     "different byte string, so none is computed")
_R_SOURCE_DETACHED = ("unverified: this snapshot was bound to exact bytes, but its content no longer matches them "
                      "(protocol_assurance.bound_snapshot_source), so it names no file")
_R_SOURCE_MALFORMED = ("unverified: the source-identity receipt failed this projection's type check (a 'sha256:' digest "
                       "of 64 lowercase hexadecimal digits and a positive byte count within the browser's exact integer "
                       "range), so it names no file")
_R_FLEET_UNREAD = ("not collected: collection_completeness carries {n} row(s) that cannot be read as a partial or "
                   "not-collected device (not an object, or a status outside its owner's vocabulary); the owner lists "
                   "only blind spots, so each could be one, and an empty list is not a clean result")
_R_FLEET_UNREADABLE_LIST = ("not collected: {path} is present but is not {kind}, so which devices it lists as partial "
                            "or not collected cannot be read; any device could be one, and an empty list is not a "
                            "clean result")
#: W51 (second round): any other reason the blind-spot record's coverage verdict (:func:`_cc_coverage`) cannot show
#: every inventory device collected or listed: an absent, failed or self-contradictory record.
_R_FLEET_CC_GAP = "not collected: {clause}; an empty list is not a clean result"
# The blind-spot record's coverage verdict (:func:`_cc_coverage`): its clauses, shared by every consumer.
_R_CC_UNREAD = "collection_completeness cannot be read ({why}), so no collection blind spot can be ruled out"
_R_CC_ROWS = ("{k} collection_completeness row(s) name no readable status of their owner's vocabulary (not an object, "
              "or a status other than partial or not collected; the owner lists only blind spots), so whether they "
              "are blind spots cannot be read")
_R_CC_SUMMARY = ("collection_completeness.summary counts {k} partial or not-collected device(s), but its devices list "
                 "carries only {n} such row(s), and the producer writes one row per such device, so a blind spot may "
                 "be missing from the list")
_R_CC_SUMMARY_UNREAD = ("collection_completeness.summary's partial or not_collected count cannot be read, so the "
                        "blind-spot list cannot be checked against it")
_R_CC_INVENTORY = ("collection_completeness.summary.inventory counts {typed} device(s), but the inventory rows (the "
                   "devices map and the blind spots the record lists) number {n}, so the record does not reconcile with "
                   "the roster and a blind spot may be missing from the list")
_R_CC_INVENTORY_UNREAD = ("collection_completeness.summary.inventory cannot be read as a count, so the record cannot be "
                          "reconciled with the roster")
_R_INVENTORY_RECORD = ("{word}: the inventory rows read the blind spots from collection_completeness, which cannot show "
                       "every inventory device collected or listed: {clauses}")


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


def _unreadable_container(doc: Any, toks: Tuple[str, ...], want: type) -> Optional[Tuple[Tuple[str, ...], type]]:
    """Where the container at the FIXED path `toks` is present but cannot be read, as ``(path, the type it should
    be)``: the first hop the snapshot carries as something other than an object, or the container itself carried as
    something other than `want`. ``None`` when it reads, or when a hop is missing or null (the abstention core's
    not_collected, never this doubt). An owner that coerces such a value to empty (ssot._as_list) reads it as
    holding nothing, so a reader that needs every row it holds treats it as rows it cannot read."""
    cur = doc
    for n, tok in enumerate(toks):
        if not isinstance(cur, dict):
            return toks[:n], dict
        cur = cur.get(tok)
        if cur is None:
            return None
    return None if isinstance(cur, want) else (toks, want)


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
        self._unjoinable: Dict[Any, List[int]] = {}
        self._pairs: Dict[Any, Dict[FrozenSet[str], List[int]]] = {}
        self._fe: Dict[Tuple[FrozenSet[str], bool], List[Tuple[str, Sequence[Any]]]] = {}
        self._census: Optional[Tuple[Optional[Dict[str, Any]], Optional[str]]] = None
        self._census_counts: Optional[Dict[str, Any]] = None
        self._mg: Optional[bool] = None
        self._cc_witness: Dict[str, List[Tuple[str, Sequence[Any]]]] = {}
        self._scope_doubt: Dict[str, Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]]] = {}
        self._blind_rows: Optional[List[int]] = None
        self._cc_cov: Optional["_CCCoverage"] = None
        self._no_config: Optional[List[str]] = None
        self._device_findings: Any = _UNSET
        self._punch_facets: Any = _UNSET
        self._vlan_hosts: Any = _UNSET
        self._coverage_rows: Any = _UNSET
        self._device_coverage: Dict[str, Optional[Dict[str, Any]]] = {}
        self._impact: Any = _UNSET
        self._source: Any = _UNSET
        self._addresses: Any = _UNSET
        self._addr_cov: Any = _UNSET

    @property
    def impact(self) -> impact_assessability.ImpactSnapshot:
        """The engine owner of failure-impact row assessability over this snapshot. It reads through this context's
        exact-key index and its envelope reading of the stored cable map, each on first use only."""
        if self._impact is _UNSET:
            self._impact = impact_assessability.ImpactSnapshot(
                self.s, rows_by_host=lambda: self.index(("failure_impact",), ("host",)),
                cables=lambda: _impact_cable_source(self))
        return self._impact

    @property
    def source(self) -> Tuple[str, Optional[str], Optional[int], str]:
        """G41: ``(state, sha256, bytes, reason)`` of the exact bytes this snapshot object was parsed from, read once
        from its owner (:data:`SNAPSHOT_IDENTITY_OWNER`), so every document built over this context agrees. A mapping
        that carries no exact-byte marker is not_collected; a marker its owner no longer verifies (the content changed
        after binding), an owner fault or a malformed receipt is unverified. Nothing here hashes the snapshot."""
        if self._source is _UNSET:
            if not isinstance(self.s, BoundSnapshot):
                self._source = (_NC, None, None, _R_SOURCE_UNBOUND)
            else:
                receipt = self._call(SNAPSHOT_IDENTITY_OWNER, bound_snapshot_source, None)
                fault = self.faults.get(SNAPSHOT_IDENTITY_OWNER)
                ok_sha, sha = _typed(receipt.get("sha256") if isinstance(receipt, dict) else None, "sha256")
                ok_n, size = _typed(receipt.get("bytes") if isinstance(receipt, dict) else None, "positive_count")
                if fault is not None:
                    self._source = (_UV, None, None, fault)
                elif not isinstance(receipt, dict) or receipt.get("source_bound") is not True:
                    self._source = (_UV, None, None, _R_SOURCE_DETACHED)
                elif not (ok_sha and ok_n):
                    self._source = (_UV, None, None, _R_SOURCE_MALFORMED)
                else:
                    self._source = (_PUB, sha, size, "")
        return self._source

    @property
    def addresses(self) -> Any:
        """The one address index (:func:`_address_sources`), built once: topology.source_addresses publishes it and
        every routing-neighbour peer resolution (G17) reads it, so the two can never disagree."""
        if self._addresses is _UNSET:
            self._addresses = _address_sources(self)
        return self._addresses

    @property
    def address_coverage(self) -> Any:
        """Whether that index holds every collected device's interface addresses, and its coverage gaps
        (:func:`_address_coverage`)."""
        if self._addr_cov is _UNSET:
            self._addr_cov = _address_coverage(self)
        return self._addr_cov

    @property
    def coverage_rows(self) -> Optional[CoverageRowIndex]:
        """One exact device/axis index over the retained rows, shared by every device fact."""
        if self._coverage_rows is _UNSET:
            self._coverage_rows = self._call(
                "coverage_matrix.index_coverage_rows",
                lambda snap: index_coverage_rows(_get(snap, ("coverage_matrix", "rows"))), None,
            )
        return self._coverage_rows

    def coverage_for(self, host: str) -> Optional[Dict[str, Any]]:
        if host not in self._device_coverage:
            rows = self.coverage_rows
            self._device_coverage[host] = self._call(
                "coverage_matrix.compute_device_coverage",
                lambda snap: compute_device_coverage(_get(snap, ("coverage_matrix", "by_device")), rows, host),
                None,
            ) if rows is not None else None
        return self._device_coverage[host]

    def _call(self, owner: str, fn: Callable[[Any], Any], fallback: Any) -> Any:
        try:
            return fn(self.s)
        except _OWNER_FAULTS as exc:
            self.faults[owner] = _fault_text(owner, exc)
            return fallback

    @property
    def device_findings(self) -> Any:
        if self._device_findings is _UNSET:
            devices = self.s.get("devices")
            hosts = sorted(k for k in devices if _is_text(k) and k.strip()) if isinstance(devices, dict) else []
            self._device_findings = self._call(
                "analyze.compute_device_findings",
                lambda snap: compute_device_findings(snap.get("punchlist"), hosts),
                {"problem": "the engine finding fold failed; its partition is unverified", "per_device": {}},
            )
        return self._device_findings

    @property
    def punch_facets(self) -> Any:
        """``analyze.compute_punchlist_facets`` over the stored punch list (computed once; ``None`` on a fault)."""
        if self._punch_facets is _UNSET:
            self._punch_facets = self._call(
                "analyze.compute_punchlist_facets",
                lambda snap: compute_punchlist_facets(snap.get("punchlist")),
                None,
            )
        return self._punch_facets

    @property
    def vlan_hosts(self) -> Any:
        if self._vlan_hosts is _UNSET:
            interfaces, roots = self.s.get("interfaces"), self.s.get("stp_roots")
            valid = isinstance(interfaces, dict) and isinstance(roots, dict)
            if valid:
                valid = all(
                    _is_text(host) and bool(host.strip()) and isinstance(ports, dict)
                    and all(_is_text(port) and isinstance(record, dict)
                            and all(record.get(field) is None or _is_text(record[field])
                                    for field in ("vlan", "switchport_mode"))
                            for port, record in ports.items())
                    for host, ports in interfaces.items()
                ) and all(
                    _is_text(host) and bool(host.strip()) and isinstance(records, dict)
                    and all(isinstance(record, dict)
                            and ("is_mst" not in record or type(record["is_mst"]) is bool)
                            for record in records.values())
                    for host, records in roots.items()
                )
            self._vlan_hosts = self._call(
                "analyze.vlan_cutover_host_index", lambda _snap: vlan_cutover_host_index(interfaces, roots), None,
            ) if valid else None
        return self._vlan_hosts

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
        is a collection blind spot (``collection_completeness`` lists it as not collected). Read it only through
        :meth:`device_scope`, which also says when its negative answer cannot be trusted."""
        return (_is_text(host) and bool(host) and self.abst_dev(section, host) == _NC
                and self.abst(section) != _NC)

    def device_scope(self, section: str, host: Any) -> Optional[Tuple[str, str, List[Tuple[str, Sequence[Any]]]]]:
        """The owner's device scope for `host`, as ``(state, reason, witness ref entries)``: ``not_collected`` when it
        calls the device a blind spot (:meth:`device_blind`); ``unverified`` when it does not, but cannot be trusted
        to say so (:meth:`scope_doubt`); ``None`` when it neither withholds nor doubts the device. Every reader of
        the device scope reads it here, so no reader can take the owner's "not a blind spot" without its doubt."""
        if self.device_blind(section, host):
            return _NC, _R_DEVICE_NC, self.cc_witness(host)
        doubt = self.scope_doubt(host)
        return None if doubt is None else (_UV, doubt[0], doubt[1])

    def scope_doubt(self, host: Any) -> Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]]:
        """Why the owner's device scope cannot be trusted to say `host` is NOT a blind spot, with a witness to each row
        that says so, or ``None``. ``ssot._device_not_collected`` is a key join over collection_completeness.devices
        (the name without case or surrounding space, first match wins) that passes over every row it cannot read, so
        it is held to the rule of every key join here (:func:`_resolve`): a row it cannot join could be this device's;
        a second row naming the device is never read; and a row whose status the owner's vocabulary does not name
        reads as collected. The record itself is held to it too, through its one coverage verdict
        (:meth:`cc_coverage`, :data:`_CC_RECORD_DOUBTS`): carried as something other than a list (or its section as
        something other than an object), the owner reads it as listing no blind spot (ssot._as_list); a failed phase
        leaves only its fallback; and a summary that counts more blind spots than the list carries, or cannot be read,
        contradicts it. Each puts every device in doubt, with a witness to that value and, for a failed phase, its
        failure record. A list or section the snapshot does not carry (missing or null) with no failure recorded is the
        abstention core's not_collected on the collection row's own state (:func:`_joins`), not a doubt about one
        device; every fleet-level reader still qualifies it (:func:`_fleet_qualify`) (cached per host)."""
        if not (_is_text(host) and host):
            return None
        if host not in self._scope_doubt:
            parts: List[str] = []
            wit: List[Tuple[str, Sequence[Any]]] = []
            for gap in self.cc_coverage().gaps:
                if gap.kind not in _CC_RECORD_DOUBTS:
                    continue
                parts.append(_R_SCOPE_LIST.format(path=".".join(gap.where[0]), kind=_KIND[gap.where[1]])
                             if gap.kind == _CC_UNREADABLE else gap.clause)
                wit += gap.entries()
            named = self.index(_CC_ROWS, ("host",), norm=True).get(_norm(host), [])
            if len(named) > 1:
                parts.append(_R_SCOPE_AMBIG.format(n=len(named)))
                wit += [("witness", _CC_ROWS + (i,)) for i in named]
            elif named:
                row = _get(self.s, _CC_ROWS + (named[0],))
                status = row.get("status") if isinstance(row, dict) else None
                if not (_is_text(status) and _norm(status) in CC_STATUSES):
                    parts.append(_R_SCOPE_STATUS.format(statuses=", ".join(CC_STATUSES)))
                    status_tok = ("status",) if isinstance(row, dict) and "status" in row else ()
                    wit.append(("witness", _CC_ROWS + (named[0],) + status_tok))
            lost = self.unjoinable(_CC_ROWS, ("host",))
            if lost:
                parts.append(_R_SCOPE_UNJOINABLE.format(n=len(lost)))
                wit += [("witness", _CC_ROWS + (i,)) for i in lost]
            self._scope_doubt[host] = (_R_SCOPE.format(parts="; ".join(parts)), wit) if parts else None
        found = self._scope_doubt[host]
        return None if found is None else (found[0], list(found[1]))

    def cc_unreadable(self) -> Optional[Tuple[Tuple[str, ...], type]]:
        """Where the blind-spot list the owner's device scope reads is present but cannot be read as a list, with the
        type it should be (:func:`_unreadable_container`), or ``None``."""
        return _unreadable_container(self.s, _CC_ROWS, list)

    def cc_coverage(self) -> "_CCCoverage":
        """The blind-spot record's one coverage verdict (:func:`_cc_coverage`), computed once: every reader of whether
        the collection reached every inventory device reads it here, never the record itself."""
        if self._cc_cov is None:
            self._cc_cov = _cc_coverage(self)
        return self._cc_cov

    def partial_row(self, host: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """The one blind-spot row the owner's device scope reads for `host` when it lists the device as partial, or
        ``(None, None)``. A doubted scope (:meth:`scope_doubt`) names no partial row: its first match may not be the
        device's own."""
        if self.scope_doubt(host) is not None:
            return None, None
        i, row = self.cc_row(host)
        status = row.get("status") if isinstance(row, dict) else None
        return (i, row) if i is not None and _is_text(status) and _norm(status) == "partial" else (None, None)

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

    def unjoinable(self, toks: Tuple[Any, ...], fields: Tuple[str, ...], multi: bool = False) -> List[int]:
        """:func:`_unjoinable_rows` of the list at `toks` (one pass, cached): the rows :meth:`index` cannot read."""
        key = (toks, fields, multi)
        if key not in self._unjoinable:
            self._unjoinable[key] = _unjoinable_rows(_get(self.s, toks), fields, multi)
        return list(self._unjoinable[key])

    def pairs(self, toks: Tuple[Any, ...], fields: Tuple[str, str]) -> Dict[FrozenSet[str], List[int]]:
        """Unordered pair of exact texts -> every row index naming it in the two `fields`, in either orientation
        (one pass, cached). A row whose two fields are not both text names no pair (:func:`_unjoinable_rows`)."""
        key = (toks, fields)
        if key not in self._pairs:
            out: Dict[FrozenSet[str], List[int]] = {}
            rows = _get(self.s, toks)
            for i, row in enumerate(rows if isinstance(rows, list) else ()):
                if isinstance(row, dict) and all(_is_text(row.get(f)) for f in fields):
                    out.setdefault(frozenset(row[f] for f in fields), []).append(i)
            self._pairs[key] = out
        return self._pairs[key]

    def blind_rows(self) -> List[int]:
        """Every collection_completeness row listing a device as partial or not collected (the owner's statuses)."""
        if self._blind_rows is None:
            rows = _get(self.s, ("collection_completeness", "devices"))
            self._blind_rows = [i for i, row in enumerate(rows if isinstance(rows, list) else ())
                                if isinstance(row, dict) and _is_text(row.get("status"))
                                and _norm(row["status"]) in CC_STATUSES]
        return list(self._blind_rows)

    def unread_blind_rows(self) -> List[int]:
        """Every collection_completeness row :meth:`blind_rows` cannot read as a partial or not-collected device (not
        an object, or a status outside its owner's vocabulary). The owner lists only blind spots, so each could be
        one; none of them is passed over silently."""
        rows = _get(self.s, _CC_ROWS)
        blind = set(self.blind_rows())
        return [i for i in range(len(rows)) if i not in blind] if isinstance(rows, list) else []

    def no_config_hosts(self) -> List[str]:
        """The devices-map hosts the security map carries no row for (no captured running-config)."""
        if self._no_config is None:
            devices, sec = self.s.get("devices"), self.s.get("security")
            self._no_config = (sorted(h for h in devices if _is_text(h) and h not in sec)
                               if isinstance(devices, dict) and isinstance(sec, dict) else [])
        return list(self._no_config)

    @property
    def mg_legacy(self) -> bool:
        """The stored membership is readable but predates producer-written labels."""
        if self._mg is None:
            self._mg = _move_group_problem(self.s.get("move_groups")) == (_NC, _R_MG)
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


#: :data:`SNAPSHOT_SHA256_PATTERN` without its anchors, for a whole-string match (``$`` would admit a trailing newline).
_SHA256_RE = re.compile(SNAPSHOT_SHA256_PATTERN[1:-1])
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
    "exposure": (("axis", "enum", DOSSIER_AXES), ("state", "enum", EXPOSURE_STATES), ("label", "text", ()),
                 ("input_state", "enum", DOSSIER_INPUT_STATES)),
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
    if slot == "exposure" and (
            (out["state"] != "na" and out["input_state"] not in (_PUB, _CBE))
            or (out["state"] == "ok" and out["input_state"] == _CBE and out["axis"] not in DOSSIER_EMPTY_IS_CLEAN)):
        return False, None
    return True, out


def _typed(raw: Any, slot: str, vocab: Sequence[str] = ()) -> Tuple[bool, Any]:
    if slot == "count":
        return _count(raw)
    if slot == "score":
        return _score(raw)
    if slot == "nonnegative_number":
        ok = (type(raw) in (int, float) and 0 <= raw <= JS_MAX_SAFE_INT
              and (not isinstance(raw, float) or math.isfinite(raw)))
        return ok, raw if ok else None
    if slot == "positive_count":
        ok, value = _count(raw)
        return ok and value > 0, value if ok and value > 0 else None
    if slot == "structural_ends":
        fields = ("a_host", "a_port", "b_host", "b_port")
        ok = isinstance(raw, dict) and all(_is_text(raw.get(k)) for k in fields)
        return ok, {k: raw[k] for k in fields} if ok else None
    if slot == "text":
        ok = _is_text(raw)
        return ok, (raw if ok else None)
    if slot == "sha256":
        ok = _is_text(raw) and _SHA256_RE.fullmatch(raw) is not None
        return ok, (raw if ok else None)
    if slot == "flag":
        return isinstance(raw, bool), (raw if isinstance(raw, bool) else None)
    if slot == "enum":
        ok = isinstance(raw, str) and raw in vocab
        return ok, (raw if ok else None)
    if slot == "text_list":
        return _text_list(raw)
    if slot == "stp_identities":
        return _stp_identities(raw)
    if slot == "fhrp":
        return (True, raw) if _is_text(raw) else _fhrp(raw)
    if slot == "coverage_cell":
        ok = isinstance(raw, str) and raw in COVERAGE_STATES
        return ok, (raw if ok else None)
    if not isinstance(raw, dict):
        return False, None
    if slot == "severity_counts":
        if set(raw) != set(SEVERITIES) or any(type(raw[severity]) is not int for severity in SEVERITIES):
            return False, None
        values = {severity: _count(raw[severity]) for severity in SEVERITIES}
        if not all(ok for ok, _value in values.values()):
            return False, None
        return True, {severity: value for severity, (_ok, value) in values.items()}
    if slot == "evidence_ref":
        keys = ("kind", "host", "ref", "role", "cite")
        host = raw.get("host")
        ok = (set(raw) == set(keys) and _is_text(raw.get("kind"))
              and raw["kind"] in PUNCH_EVIDENCE_REF_KINDS and _is_text(raw.get("role"))
              and raw["role"] in PUNCH_EVIDENCE_ROLES
              and (host is None or (_is_text(host) and bool(host.strip())))
              and _is_text(raw.get("ref")) and bool(raw["ref"])
              and re.fullmatch(r"(/([^~/]|~[01])*)+", raw["ref"]) is not None
              and _is_text(raw.get("cite")))
        return ok, ({key: raw[key] for key in keys} if ok else None)
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


def _fleet_health_count(ctx: _Ctx, key: str, caveats: Sequence[str] = ()) -> Dict[str, Any]:
    """``ssot.fleet_avg_health``'s ``n_scored`` or ``n_rows``: a live count over the health rows (no snapshot
    address). One builder for the fleet-health block and the Fleet health axis's could-not-assess count."""
    hs_t = ctx.abst("health_scores")
    health = ctx.s.get("health_scores")
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
        ok, value = _count(ctx.fh.get(key))
        state = _PUB if ok else _UV
    refs = ctx.refs(entries + ctx.failure_entries(("health_scores",), state == AU))
    return _envelope(state, value, None, refs, f"ssot.fleet_avg_health:{key}",
                     reason or _state_reason(ctx, state, "count", ("health_scores",)),
                     caveats=caveats if state == _PUB else ())


def _fleet_health(ctx: _Ctx, avg: Dict[str, Any]) -> Dict[str, Any]:
    fh = ctx.fh
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
        block[key] = _fleet_health_count(ctx, key)
    block["bands"] = _health_bands(ctx)
    return block


def _health_bands(ctx: _Ctx) -> List[Dict[str, Any]]:
    """The SSOT owner's unpersisted partition, separate from the fleet-average domain state."""
    order = HEALTH_BANDS + (HEALTH_BAND_NOT_SCORED,)
    state, reason, raw = _PUB, None, None
    hit = _secs_fail(ctx, ("health_scores",))
    if hit:
        state, reason = hit
    else:
        try:
            partition = ssot.health_band_partition(ctx.s)
            violations = ssot.reconcile_health_band_partition(ctx.s, partition)
            state, reason, raw = partition["state"], partition["reason"], partition["bands"]
            if violations:
                state, reason = _UV, "unverified: ssot.reconcile_health_band_partition rejects the partition: " + "; ".join(violations)
        except _OWNER_FAULTS as exc:
            state, reason = _UV, _fault_text("ssot.health_band_partition", exc)
    if state not in (_PUB, _NC, _UV, AU):
        state, reason = _UV, "unverified: the health partition owner returned an unknown evidence state"
    valid = (isinstance(raw, list) and len(raw) == len(order)
             and all(isinstance(r, dict) and r.get("band") == band and _count(r.get("n"))[0]
                     and _text_list(r.get("hosts"))[0] and r["n"] == len(r["hosts"])
                     for band, r in zip(order, raw)))
    if state == _PUB and not valid:
        state, reason = _UV, "unverified: the health partition owner returned malformed bands"
    rows: List[Dict[str, Any]] = []
    for i, band in enumerate(order):
        band_state, band_reason = state, reason
        if state == _PUB and band != HEALTH_BAND_NOT_SCORED and ctx.fh.get("n_scored") == 0:
            band_state, band_reason = _NA, _not_assessed_reason(ctx)
        elif state == _PUB and band in ("Critical", "Poor"):
            name = "n_critical" if band == "Critical" else "n_poor"
            path = ssot.CANONICAL_FACTS[name][0]
            canonical = _scalar(ctx, path, "count", "ssot.canonical_facts:" + path, posture_name=name)
            if canonical["state"] != _PUB:
                band_state, band_reason = canonical["state"], canonical["reason"]
        refs = ctx.refs([("basis", ("health_scores",))]
                        + ctx.failure_entries(("health_scores",), band_state == AU))
        rec = raw[i] if valid else {}
        host_state = _CBE if band_state == _PUB and not rec.get("hosts") else band_state
        host_reason = _R_CBE if host_state == _CBE else band_reason
        caveats = ("health_band_partition_rows_only",) + _one_hop(ctx, band_state, ("health_scores",))
        rows.append({"band": band,
                     "n": _envelope(band_state, _count(rec.get("n"))[1], None, refs,
                                    "ssot.health_band_partition:n",
                                    band_reason or _state_reason(ctx, band_state, "count", ("health_scores",)),
                                    caveats=caveats if band_state == _PUB else ()),
                     "hosts": _envelope(host_state, list(rec.get("hosts", [])), None, refs,
                                        "ssot.health_band_partition:hosts",
                                        host_reason or _state_reason(ctx, host_state, "text_list", ("health_scores",)),
                                        caveats=caveats if host_state in (_PUB, _CBE) else ())})
    return rows


def _readiness_problem(raw: Any, groups: Any) -> Optional[Tuple[str, str]]:
    """A published checklist must join by the written identity and obey the producer's verdict rule."""
    problem = _move_group_problem(groups)
    if problem:
        return problem
    if not isinstance(raw, list):
        return _NC, "not collected: no migration-readiness list was published"
    labels = [r.get("group") if isinstance(r, dict) else None for r in raw]
    if (not all(_is_text(label) and label.strip() for label in labels)
            or len(set(labels)) != len(labels)):
        return _UV, "unverified: migration-readiness identities are malformed or duplicated"
    expected = {g[MOVE_GROUP_LABEL]: g for g in groups}
    if set(labels) != set(expected):
        return _UV, "unverified: migration-readiness rows do not cover exactly the published move groups"
    for rec in raw:
        group = expected[rec["group"]]
        if not group["switches"] or rec.get("switches") != group["switches"]:
            return _UV, "unverified: migration-readiness membership contradicts the labelled move group"
        if "endpoints" not in group or "endpoints" not in rec:
            return _NC, "not collected: the labelled move group or readiness row carries no endpoint count"
        if (not _count(group["endpoints"])[0] or not _count(rec["endpoints"])[0]
                or rec["endpoints"] != group["endpoints"]):
            return _UV, "unverified: migration-readiness endpoints contradict the labelled move group"
        if any(key not in rec for key in ("readiness", "n_fail", "n_warn", "checks")):
            return _NC, "not collected: the migration-readiness row carries no complete verdict and checklist"
        checks = rec["checks"]
        if not isinstance(checks, list) or not checks:
            return _UV, "unverified: migration readiness has no readable, non-empty checklist"
        if not all(isinstance(c, dict) and _is_text(c.get("check")) and c["check"].strip()
                   and isinstance(c.get("status"), str) and c["status"] in READINESS_CHECK_STATUSES
                   and _is_text(c.get("note")) and _is_text(c.get("phase")) for c in checks):
            return _UV, "unverified: a migration-readiness check is malformed"
        if len({c["check"] for c in checks}) != len(checks):
            return _UV, "unverified: a migration-readiness check identity is duplicated"
        statuses = [c["status"] for c in checks]
        verdict = "NOT READY" if "fail" in statuses else "CAUTION" if "warn" in statuses else "READY"
        if (not _count(rec["n_fail"])[0] or not _count(rec["n_warn"])[0]
                or rec["n_fail"] != statuses.count("fail") or rec["n_warn"] != statuses.count("warn")
                or rec["readiness"] != verdict):
            return _UV, "unverified: migration-readiness counts or verdict contradict the published checks"
    return None


def _readiness(ctx: _Ctx) -> Dict[str, Any]:
    """Publish the owner's checklist without inventing labels or repairing a verdict."""
    sections = ("migration_readiness", "move_groups")
    state, reason, raw = _list_state(ctx, ("migration_readiness",), sections)
    failure = _secs_fail(ctx, READINESS_INPUTS)
    if failure:
        state, reason = failure
    problem = _readiness_problem(raw, ctx.s.get("move_groups")) if state in (_PUB, _CBE) else None
    if problem:
        state, reason = problem
    if state in (_PUB, _CBE) and raw:
        for section, want in (("interfaces", dict), ("health_scores", list)):
            value = ctx.s.get(section)
            if value is None or (isinstance(value, want) and not value):
                state, reason = _NC, f"not collected: migration-readiness core input {section} carries no evidence"
                break
            if not isinstance(value, want):
                state, reason = _UV, f"unverified: migration-readiness core input {section} is malformed"
                break
    rows: List[Dict[str, Any]] = []
    groups = ctx.s.get("move_groups")
    labels = ({g[MOVE_GROUP_LABEL]: i for i, g in enumerate(groups)}
              if isinstance(groups, list) and _move_group_problem(groups) is None else {})
    for i, rec in enumerate(raw if isinstance(raw, list) else ()):
        toks = ("migration_readiness", i)
        row = _Row(None if state == _PUB else state, reason, toks, rec, sections,
                   extra=[("basis", (s,)) for s in READINESS_INPUTS]
                   + ctx.failure_entries(READINESS_INPUTS, state == AU))
        if row.state is None and not isinstance(rec, dict):
            row = _Row(_UV, _R_NOT_OBJECT, toks, rec, sections)
        item: Dict[str, Any] = {"index": i, "pointer": json_pointer(*toks)}
        for field, slot, vocab in (("group", "text", ()), ("readiness", "enum", VLAN_READINESS),
                                   ("switches", "text_list", ()), ("endpoints", "count", ()),
                                   ("n_fail", "count", ()), ("n_warn", "count", ())):
            witness: List[Tuple[str, Sequence[Any]]] = []
            label = rec.get("group") if isinstance(rec, dict) else None
            if isinstance(label, str) and label in labels:
                joined_field = field if field in ("group", "switches", "endpoints") else "group"
                witness.append(("witness", ("move_groups", labels[label], joined_field)))
            item[field] = _cell(ctx, row, field, slot, "analyze.compute_migration_readiness:" + field,
                                vocab=vocab, witness=witness,
                                published_caveats=(("move_group_endpoints_not_distinct",) if field == "endpoints"
                                                   else ("migration_readiness_check_scope",) if field == "readiness"
                                                   else ()))
        cs, cr, ct, checks = _sub_list(ctx, row, "checks")
        check_rows: List[Dict[str, Any]] = []
        for j, check in enumerate(checks if isinstance(checks, list) else ()):
            tt = toks + ("checks", j)
            check_row = _Row(None if cs == _PUB else cs, cr, tt, check, sections)
            entry = {"index": j, "pointer": json_pointer(*tt)}
            for field in ("check", "status", "note", "phase"):
                entry[field] = _cell(ctx, check_row, field, "enum" if field == "status" else "text",
                                     "analyze.compute_migration_readiness:checks." + field,
                                     vocab=READINESS_CHECK_STATUSES if field == "status" else ())
            check_rows.append(entry)
        item["checks"] = _listing(ctx, cs, cr, ct, "analyze.compute_migration_readiness:checks",
                                   check_rows, sections=sections)
        rows.append(item)
    caveats = ("move_group_endpoints_not_distinct", "migration_readiness_check_scope") + (
        ("move_group_label_absent",) if ctx.mg_legacy else ())
    return {"groups": _listing(ctx, state, reason, ("migration_readiness",),
                                "analyze.compute_migration_readiness", rows, sections=sections,
                                rollup=("move_groups",), caveats=caveats,
                                extra=[("basis", (s,)) for s in READINESS_INPUTS]
                                + ctx.failure_entries(READINESS_INPUTS, state == AU))}


# ---------------------------------------------------------------------------------------------------
# G05: per axis, the devices it could not assess, out of how many -- read from the axis's producer
# ---------------------------------------------------------------------------------------------------
_B_AXIS_TABLE = "cisco_toolkit.ui_projection.AXIS_UNASSESSED"
_B_AXIS_ABSENT = "cisco_toolkit.ui_projection.AXIS_UNASSESSED_ABSENT"
_B_FLEET_UNSCORED = "ssot.fleet_avg_health:n_rows - n_scored"
_R_AXIS_NO_LABEL = ("unverified: the axis row carries no readable label, so no producer count of the devices it could "
                    "not assess can be chosen")
_R_AXIS_UNREGISTERED = ("not collected: this projection registers no producer count of the devices this axis label "
                        "could not assess, so nothing is claimed for it; it is never shown as 0")
_R_COVERED_NONE = ("collected but empty: the producer covered no device, so no device was left unassessed and none "
                   "was assessed (not a blind spot)")
#: While collection_completeness lists a blind spot (fleet_lists_exclude_blind_devices): a zero count, a count over no
#: device, and an empty denominator are not clean results, because no producer universe holds an unreached device.
_R_AXIS_BLIND_N = ("not collected: collection_completeness lists {k} device(s) as partial or not collected, and this "
                   "axis's producer counts only the devices whose evidence it was given (a device the collection never "
                   "reached is in neither this count nor its denominator), so its count cannot show that every "
                   "inventory device was assessed; it is never shown as 0")
_R_AXIS_BLIND_OF = ("not collected: collection_completeness lists {k} device(s) as partial or not collected, and this "
                    "axis's producer covered no device: its device count holds only the devices whose evidence it was "
                    "given, so an empty count is not a clean result; it is never shown as 0")
#: W51 (F6 x G05): the same two holds for a fleet qualification that is not a readable blind-spot row (a row or list
#: the blind-spot classifier cannot read), worded by that qualification's own reason, never as "lists 0 device(s)".
_R_AXIS_UNREAD_N = ("{why}; this axis's producer counts only the devices whose evidence it was given, so its count "
                    "cannot show that every inventory device was assessed; it is never shown as 0")
_R_AXIS_UNREAD_OF = ("{why}; this axis's producer covered no device, and its device count holds only the devices whose "
                     "evidence it was given, so an empty count is not a clean result; it is never shown as 0")
#: One could-not-assess entry: ``(producer, count, denominator, rows, field, value)`` (see :data:`AXIS_UNASSESSED`).
_UnassessedSpec = Tuple[str, str, str, str, str, Union[str, bool]]


def _unassessed_rows(ctx: _Ctx, rows_path: str, field: str, mark: Union[str, bool]) -> Tuple[Optional[bool], int, int]:
    """A count's raw basis: ``(readable, rows, rows whose `field` is `mark`)``. ``readable`` is ``None`` when the
    producer's per-device rows are absent (nothing to check the count against) and ``False`` when they are present but
    are not a list of records each carrying `field` with the type of `mark`."""
    rows = _get(ctx.s, _tokens(rows_path))
    if rows is _MISSING or rows is None:
        return None, 0, 0
    kind = type(mark)
    if not isinstance(rows, list) or not all(isinstance(row, dict) and type(row.get(field)) is kind for row in rows):
        return False, 0, 0
    return True, len(rows), sum(1 for row in rows if row[field] == mark)


def _missing_unassessed(ctx: _Ctx, spec: _UnassessedSpec, of: Dict[str, Any], cav: Tuple[str, ...],
                        rows: Tuple[Optional[bool], int, int],
                        doubt: Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]]) -> Dict[str, Any]:
    """The count's entry is absent from a summary its producer did write. A counter that omits an entry no device
    holds (:data:`AXIS_UNASSESSED_SPARSE`) reads as zero only when its per-device rows and a published device count
    confirm that none carries the value; any other absence is a count this snapshot does not store."""
    owner, n_path, of_path, rows_path, field, mark = spec
    n_toks, of_toks, rows_toks = _tokens(n_path), _tokens(of_path), _tokens(rows_path)
    parent_path, leaf = ".".join(n_toks[:-1]), n_toks[-1]
    basis = f"{owner}:{n_path}"
    readable, marked = rows[0], rows[2]
    witness: List[Tuple[str, Sequence[Any]]] = [("witness", n_toks[:-1]), ("witness", rows_toks)]
    if parent_path not in AXIS_UNASSESSED_SPARSE:
        return _envelope(_NC, None, json_pointer(*n_toks), ctx.refs(witness[:1]), basis,
                         f"not collected: {parent_path} stores no {leaf} (for example a snapshot that predates this "
                         "count, or a summary edited after it was written), so how many devices this axis could not "
                         "assess is not known; it is never shown as 0")
    if doubt:
        return _envelope(_UV, None, json_pointer(*n_toks), ctx.refs(witness + doubt[1]), basis, doubt[0])
    if readable and marked:
        return _envelope(_UV, None, json_pointer(*n_toks), ctx.refs(witness), basis,
                         f"unverified: {parent_path} stores no {leaf} entry, yet {marked} of the rows in {rows_path} "
                         f"carry {field} {mark!r}")
    if readable and of["state"] == _PUB:
        refs = ctx.refs(witness + [("denominator", of_toks)])
        live = f"{basis} (an entry its counter omits; zero confirmed by {rows_path})"
        if of["value"] == 0:
            return _envelope(_CBE, None, None, refs, live, _R_COVERED_NONE)
        return _envelope(_PUB, 0, None, refs, live, "", caveats=cav)
    return _envelope(_NC, None, json_pointer(*n_toks), ctx.refs(witness), basis,
                     f"not collected: {parent_path} stores no {leaf} entry, which its producer omits when no device "
                     f"holds it, and {rows_path} with a published device count cannot confirm that here, so the count "
                     "is not known; it is never shown as 0")


def _stored_unassessed(ctx: _Ctx, label: str, spec: _UnassessedSpec, cav: Tuple[str, ...]) -> Dict[str, Any]:
    """The producer's stored count and denominator, each through :func:`_scalar` (failure, blind spot, type and
    reconcile rules), then held against each other, against a further layer's stored count
    (:data:`AXIS_UNASSESSED_LAYERS`) and against the producer's per-device rows: any disagreement withholds both as
    unverified, and a zero over a zero denominator is no measurement."""
    owner, n_path, of_path, rows_path, field, mark = spec
    n_toks, of_toks = _tokens(n_path), _tokens(of_path)
    rows = _unassessed_rows(ctx, rows_path, field, mark)
    readable, total, marked = rows
    n_raw = _get(ctx.s, n_toks)
    n_ok, n_val = _count(n_raw)
    of_ok, of_val = _count(_get(ctx.s, of_toks))
    over: List[Tuple[str, int]] = []                # a further layer's count above the device count
    off: List[Tuple[Tuple[Any, ...], Any, int]] = []   # a further layer's count its own per-device rows contradict
    for layer in AXIS_UNASSESSED_LAYERS.get(label, ()):
        layer_ok, layer_val, layer_marked, present = _layer_count(ctx, layer)
        if layer_ok and of_ok and layer_val > of_val:
            over.append((layer[0], layer_val))
        elif layer_ok and layer_marked is not None and layer_marked != layer_val:
            off.append((layer, layer_val if present else None, layer_marked))
    doubt: Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]] = None
    if n_ok and of_ok and n_val > of_val:
        doubt = (f"unverified: the producer's count of devices this axis could not assess ({n_val}) exceeds its own "
                 f"device count ({of_val})", [("witness", n_toks), ("witness", of_toks)])
    elif over:
        doubt = (f"unverified: the producer's count of the devices a further layer of this axis could not assess "
                 f"({over[0][0]}: {over[0][1]}) exceeds its own device count ({of_val})",
                 [("witness", _tokens(over[0][0])), ("witness", of_toks)])
    elif readable is False:
        doubt = (f"unverified: {rows_path} cannot be read as per-device records each carrying {field}, so the "
                 "stored count cannot be checked against its raw basis", [("witness", _tokens(rows_path))])
    elif readable and ((of_ok and total != of_val) or (n_ok and marked != n_val)):
        stored = (f"{n_val}" if n_ok else "no readable count") + " of " + (
            f"{of_val}" if of_ok else "no readable device count")
        doubt = (f"unverified: {rows_path} holds {total} device row(s), {marked} of them with {field} {mark!r}, "
                 f"while the producer's summary stores {stored}", [("witness", _tokens(rows_path))])
    elif off:
        (lpath, _lname, lrows, lfield, lmark, _cover), stored_val, lmarked = off[0]
        stored_txt = "no entry" if stored_val is None else str(stored_val)
        doubt = (f"unverified: the producer's count of the devices a further layer of this axis could not assess "
                 f"({lpath}: {stored_txt}) disagrees with its per-device rows ({lmarked} of the rows in {lrows} carry "
                 f"{lfield} {lmark!r})", [("witness", _tokens(lpath)[:-1]), ("witness", _tokens(lrows))])

    def of_gate(_ctx: _Ctx, _value: Any, _zero: bool):
        return (_UV, doubt[0], list(doubt[1])) if doubt else None

    def n_gate(_ctx: _Ctx, typed: Any, _zero: bool):
        if doubt:
            return _UV, doubt[0], list(doubt[1])
        if typed == 0 and of_ok and of_val == 0:
            return _CBE, _R_COVERED_NONE, []
        return None

    of = _scalar(ctx, of_path, "count", f"{owner}:{of_path}", gate=of_gate, published_caveats=cav)
    # A missing entry the abstention core calls a blind spot (not a failed phase or an owner fault) inside a summary
    # the producer did write: a sparse counter's zero, or a count this snapshot does not store.
    if n_raw is _MISSING and isinstance(_get(ctx.s, n_toks[:-1]), dict) and ctx.abst(n_path) == _NC:
        n = _missing_unassessed(ctx, spec, of, cav, rows, doubt)
    else:
        n = _scalar(ctx, n_path, "count", f"{owner}:{n_path}", gate=n_gate, witness=[("denominator", of_toks)],
                    published_caveats=cav)
    return {"n": n, "of": of}


def _fleet_unassessed(ctx: _Ctx, cav: Tuple[str, ...]) -> Dict[str, Any]:
    """Fleet health: the brief's unscored health rows, ``ssot.fleet_avg_health``'s ``n_rows`` minus ``n_scored`` (the
    predicate the brief averages over), out of ``n_rows``; the same live counts the fleet-health block publishes."""
    of = _fleet_health_count(ctx, "n_rows", caveats=cav)
    scored = _fleet_health_count(ctx, "n_scored")
    refs = [dict(ref) for ref in of["refs"]] + [dict(ref) for ref in scored["refs"] if ref not in of["refs"]]
    if of["state"] != _PUB or scored["state"] != _PUB:
        source = of if of["state"] != _PUB else scored
        n = _envelope(source["state"], None, None, refs, _B_FLEET_UNSCORED, source["reason"])
    elif scored["value"] > of["value"]:
        n = _envelope(_UV, None, None, refs, _B_FLEET_UNSCORED,
                      "unverified: ssot.fleet_avg_health counts more scored health rows than health rows")
    elif of["value"] == 0:
        n = _envelope(_CBE, None, None, refs, _B_FLEET_UNSCORED,
                      "collected but empty: the snapshot publishes no health row, so no row was left unscored and "
                      "none was scored (not a blind spot)")
    else:
        n = _envelope(_PUB, of["value"] - scored["value"], None, refs, _B_FLEET_UNSCORED, "", caveats=cav)
    return {"n": n, "of": of}


def _failed_unassessed(ctx: _Ctx, label: Optional[str], basis: Sequence[str]) -> Dict[str, Any]:
    """Both cells of a row whose fact a failed phase makes analysis_unavailable (the brief itself, or an input the row's
    basis names): the same verdict and the same failure records as the fact beside them, whatever the label."""
    sections = ("executive_brief",) + tuple(basis)
    reason = ctx.unavailable_reason(sections)
    failure = ctx.failure_entries(sections, True)
    spec = AXIS_UNASSESSED.get(label) if label is not None else None
    cells: List[Tuple[str, Optional[Tuple[str, ...]]]]
    if spec is not None:
        cells = [(f"{spec[0]}:{spec[1]}", _tokens(spec[1])), (f"{spec[0]}:{spec[2]}", _tokens(spec[2]))]
    elif label is not None and label in AXIS_UNASSESSED_LIVE:
        cells = [(_B_FLEET_UNSCORED, None), ("ssot.fleet_avg_health:n_rows", None)]
    else:
        name = _B_AXIS_ABSENT if label is not None and label in AXIS_UNASSESSED_ABSENT else _B_AXIS_TABLE
        cells = [(name, None), (name, None)]
    out: Dict[str, Any] = {}
    for key, (name, subject) in zip(("n", "of"), cells):
        entries = (([("subject", subject)] if subject else []) + [("basis", (s,)) for s in basis] + list(failure))
        out[key] = _envelope(AU, None, json_pointer(*subject) if subject else None, ctx.refs(entries), name, reason,
                             owner_token=ctx.abst(".".join(subject)) if subject else None)
    return out


def _layer_count(ctx: _Ctx, layer: Tuple[str, str, str, str, Union[str, bool], str]
                 ) -> Tuple[bool, Any, Optional[int], bool]:
    """A further layer's own could-not-assess count (:data:`AXIS_UNASSESSED_LAYERS`): ``(readable, value, rows carrying
    the could-not-assess value or None when its per-device rows cannot be read, whether the entry is stored)``. A
    counter that omits an entry no device holds (:data:`AXIS_UNASSESSED_SPARSE`) reads a missing entry as zero only
    when its per-device rows can be read, and then the rows say what it should hold."""
    layer_path, _name, rows_path, field, mark, _cover = layer
    toks = _tokens(layer_path)
    readable, _total, marked = _unassessed_rows(ctx, rows_path, field, mark)
    rows_marked = marked if readable else None
    raw = _get(ctx.s, toks)
    if raw is _MISSING and isinstance(_get(ctx.s, toks[:-1]), dict) and ".".join(toks[:-1]) in AXIS_UNASSESSED_SPARSE:
        return (True, 0, rows_marked, False) if readable else (False, None, None, False)
    ok, value = _count(raw)
    return ok, value, rows_marked, raw is not _MISSING


def _layer_gaps(ctx: _Ctx, label: Optional[str], n: Dict[str, Any],
                of: Dict[str, Any]) -> List[Tuple[str, List[Tuple[str, Sequence[Any]]]]]:
    """``(reason, witness entries)`` for each further layer of the axis (:data:`AXIS_UNASSESSED_LAYERS`) whose own
    could-not-assess count (:func:`_layer_count`) is above zero, or cannot be read over a published device count: the
    registered count then covers one layer only, and the producer stores none that spans every layer. A layer's
    coverage key (a release captured) never stands in for its own count (a release classified)."""
    out: List[Tuple[str, List[Tuple[str, Sequence[Any]]]]] = []
    for layer in (AXIS_UNASSESSED_LAYERS.get(label, ()) if label is not None else ()):
        layer_path, name = layer[0], layer[1]
        layer_toks = _tokens(layer_path)
        layer_ok, layer_val, _marked, present = _layer_count(ctx, layer)
        if layer_ok and of["state"] == _PUB and layer_val == 0:
            continue
        held = f" ({n['value']})" if n["state"] == _PUB else ""
        if layer_ok and of["state"] == _PUB and 0 < layer_val <= of["value"]:
            why = (f"not collected: this count{held} covers one layer of the axis only; its {name} could not assess "
                   f"{layer_val} of the {of['value']} device(s) ({layer_path} is {layer_val}), and the producer stores "
                   "no count of the devices it could not assess in every layer, so how many devices this axis could "
                   "not assess is not known; it is never shown as 0")
        else:
            why = (f"not collected: this count{held} covers one layer of the axis only, and {layer_path} is not a "
                   f"readable count over a published device count, so whether its {name} assessed every device is "
                   "not known; it is never shown as 0")
        out.append((why, [("witness", layer_toks if present else layer_toks[:-1])]))
    return out


def _withheld_count(ctx: _Ctx, fact: Dict[str, Any], holds: Sequence[Tuple[str, Sequence[Tuple[str, Sequence[Any]]]]],
                    owner_token: Optional[str]) -> Dict[str, Any]:
    """`fact` withheld as not_collected for every reason in `holds`, with its refs and each hold's witness refs; the
    owner's own token for the stored value stays in ``engine_state``."""
    refs = [dict(ref) for ref in fact["refs"]]
    for ref in ctx.refs([entry for _why, wit in holds for entry in wit]):
        if ref not in refs:
            refs.append(ref)
    return _envelope(_NC, None, fact["subject"], refs, fact["basis"], "; ".join(why for why, _wit in holds),
                     owner_token=owner_token)


def _caveated_count(ctx: _Ctx, fact: Dict[str, Any], caveat: str,
                    witness: Sequence[Tuple[str, Sequence[Any]]]) -> Dict[str, Any]:
    """A published `fact` that also carries `caveat`, with `witness` refs added."""
    out = dict(fact)
    refs = [dict(ref) for ref in fact["refs"]]
    for ref in ctx.refs(witness):
        if ref not in refs:
            refs.append(ref)
    out["refs"] = refs
    kept = set(fact.get("caveats", ())) | {caveat}
    out["caveats"] = [c for c in _ALL_LIMITATION_IDS if c in kept]
    return out


def _qualify_unassessed(ctx: _Ctx, label: str, block: Dict[str, Any],
                        owner_tokens: Tuple[Optional[str], Optional[str]]) -> Dict[str, Any]:
    """Two qualifications no producer count carries itself. A further layer the count does not cover
    (:data:`AXIS_UNASSESSED_LAYERS`) withholds ``n``. A listed collection blind spot (the fleet-list qualification,
    :func:`_fleet_qualify`) puts its caveat and a witness ref to each blind-spot row on a published count or denominator
    and withholds a zero count, a count over no device and an empty denominator: no producer universe holds an
    unreached device, so none of them is a clean result."""
    n, of = block["n"], block["of"]
    blind = _fleet_qualify(ctx)
    n_blind = len(ctx.blind_rows())
    # the readable blind-spot rows are counted as devices; any other qualification (F6: a row or list the blind-spot
    # classifier cannot read) keeps its own reason
    counted = _R_FLEET_BLIND.format(n=n_blind)

    def blind_hold(why: str, wit: Sequence[Tuple[str, Sequence[Any]]], listed: str,
                   unread: str) -> Tuple[str, Sequence[Tuple[str, Sequence[Any]]]]:
        return (listed.format(k=n_blind) if why == counted else unread.format(why=why)), wit

    holds: List[Tuple[str, Sequence[Tuple[str, Sequence[Any]]]]] = []
    if n["state"] == _PUB:                       # a count over no device has no layer left unassessed
        holds.extend(_layer_gaps(ctx, label, n, of))
    if n["state"] in (_PUB, _CBE):
        if blind and (holds or n["state"] == _CBE or n["value"] == 0):
            holds.extend(blind_hold(why, wit, _R_AXIS_BLIND_N, _R_AXIS_UNREAD_N) for _cid, why, wit in blind)
    if holds:
        n = _withheld_count(ctx, n, holds, owner_tokens[0])
    elif blind and n["state"] == _PUB:
        for cid, _why, wit in blind:
            n = _caveated_count(ctx, n, cid, wit)
    if blind and (of["state"] == _CBE or (of["state"] == _PUB and of["value"] == 0)):
        of = _withheld_count(ctx, of, [blind_hold(why, wit, _R_AXIS_BLIND_OF, _R_AXIS_UNREAD_OF)
                                       for _cid, why, wit in blind], owner_tokens[1])
    elif blind and of["state"] == _PUB:
        for cid, _why, wit in blind:
            of = _caveated_count(ctx, of, cid, wit)
    return {"n": n, "of": of}


def _axis_unassessed(ctx: _Ctx, label: Optional[str], toks: Tuple[Any, ...], basis: Sequence[str],
                     base: str) -> Dict[str, Any]:
    """G05: how many devices this axis could not assess (``n``), out of how many (``of``), read from the axis's producer
    (:data:`AXIS_UNASSESSED`, :data:`AXIS_UNASSESSED_LIVE`), never from its headline, then qualified by the further
    layers it does not cover and by the collection blind spots no producer universe holds
    (:func:`_qualify_unassessed`). `basis` and `base` are the row's own: a failed input that makes the row's fact
    analysis_unavailable makes both cells so too. An axis whose producer stores no such count
    (:data:`AXIS_UNASSESSED_ABSENT`) or an unregistered label is not_collected, never 0; a row with no readable label
    is unverified."""
    if base == AU or _item_basis_state(ctx, basis)[0] == AU:
        return _failed_unassessed(ctx, label, basis)              # a failed input always wins, row and block alike
    cav = _brief_caveats(ctx, "axis_basis_owned_by_projection")
    if label is not None and label in AXIS_UNASSESSED_LIVE:
        return _qualify_unassessed(ctx, label, _fleet_unassessed(ctx, cav), (None, None))
    spec = AXIS_UNASSESSED.get(label) if label is not None else None
    if spec is not None:
        return _qualify_unassessed(ctx, label, _stored_unassessed(ctx, label, spec, cav),
                                   (ctx.abst(spec[1]), ctx.abst(spec[2])))
    name = _B_AXIS_TABLE
    if label is None:
        state, reason, entries = _UV, _R_AXIS_NO_LABEL, [("witness", toks)]
    else:
        why = AXIS_UNASSESSED_ABSENT.get(label)
        state, entries = _NC, [("basis", (s,)) for s in basis]
        if why:
            name = _B_AXIS_ABSENT
            reason = (f"not collected: {why}; how many devices this axis could not assess is not stored, so it is "
                      "never shown as 0")
        else:
            reason = _R_AXIS_UNREGISTERED
    refs = ctx.refs(entries)
    return {"n": _envelope(state, None, None, refs, name, reason),
            "of": _envelope(state, None, None, [dict(ref) for ref in refs], name, reason)}


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
        items.append({"index": i, "axis": label, "basis_sections": list(basis), "fact": fact,
                      "unassessed": _axis_unassessed(ctx, label, toks, basis, base)})
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
        "readiness": _readiness(ctx),
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


# ---------------------------------------------------------------------------------------------------
# trust: the analysis-input gap summary (G08)
#
# The engine's per-device custody of each analysis input is the risk register's exposure record: for every device
# row, analyze.compute_device_dossiers writes exactly one {axis, state, label, input_state} per entry of
# analyze.DOSSIER_AXIS_INPUTS, and forces state 'na' whenever the input was not published (its ax()). The register
# writes a row for every device the devices map names: its host universe includes lifecycle_risk.per_device, which
# compute_lifecycle_risk writes for every key of the same device-physical map the devices map is built from. No
# findings-only or sparse section is read for absence here; its absence is never a gap and never clean. A register
# row the exact-key join cannot read (:func:`_unjoinable_rows`) could be any listed device's row, so it withholds
# every count, the precedent of the strict device selection.
# ---------------------------------------------------------------------------------------------------
#: Every analysis input the engine assesses PER DEVICE, with its input sections, in the owner's order: the risk
#: register's closed axis registry (analyze.DOSSIER_AXIS_INPUTS), imported, never copied.
TRUST_INPUTS: Mapping[str, Tuple[str, ...]] = MappingProxyType(
    {axis: tuple(sections) for axis, sections in DOSSIER_AXIS_INPUTS.items()})
#: Why an input did not assess a listed device: the dossier's input state for an 'na' axis, not_collected for a
#: collection blind spot, analysis_unavailable or unverified when no single readable exposure exists. Every token is
#: an absence, so the G43 catalogue (``_VOCAB_UNRANKED``) names it as an unranked vocabulary that draws no level.
TRUST_INPUT_CUSTODY: Tuple[str, ...] = tuple(s for s in WITHHELD_STATES if s != _NA)
_B_INPUTS = ("analyze.compute_device_dossiers:device_dossiers.per_device[].exposures[] + "
             "analyze.compute_collection_completeness:collection_completeness.devices[]")
_R_INPUTS_ASSESSED = ("collected but empty: every inventory device carries one readable exposure for this input that "
                      "is not 'na' (not a blind spot)")
_R_INPUTS_NO_DEVICE = ("not collected: the inventory names no device (neither the devices map nor "
                       "collection_completeness), so no input assessed anything and a zero would claim nothing")
_R_INPUTS_NO_REGISTER = ("not collected: the snapshot carries no device_dossiers.per_device, so no device's custody "
                         "of this input is published; only collection blind spots are listed, and an absent device "
                         "is not a clean result")
_R_INPUTS_UNJOINABLE = _R_UNJOINABLE_STEM + ("any inventory device, so the count of devices this input could not "
                                             "assess is not verified")
#: W51 (F6 x G08): a device whose owner device scope cannot say it is not a blind spot (:meth:`_Ctx.device_scope`).
_R_INPUTS_SCOPE = ("unverified: whether collection_completeness lists {n} device(s) as partial or not collected cannot "
                   "be read (a row the host join cannot read, a second row naming the device, a status outside its "
                   "owner's vocabulary, or a record that failed or whose summary counts a blind spot its list does not "
                   "carry; ssot.abstention_reason reads only the first row it can), so the count of devices this input "
                   "could not assess is not verified")
#: W51: the blind-spot record cannot show which inventory devices were not collected (:func:`_roster_gaps`).
_R_INPUTS_RECORD = ("{word}: collection_completeness, which lists the inventory devices no input could assess, cannot "
                    "show every inventory device collected or listed: {clauses}; so the count of devices this input "
                    "could not assess is not verified")
#: How one inventory device stands before any axis is read: ``(fixed custody, witness pointer, why)`` when the same
#: custody holds for every input, else ``None`` with the dossier row and its axis index.
_HostCustody = Tuple[Optional[Tuple[str, str, str]], Optional[Tuple[Tuple[Any, ...], List[Any], Dict[str, List[int]]]]]


def _host_custody(ctx: _Ctx, host: str, dev_keys: FrozenSet[str], index: Mapping[str, List[int]], raw: Any,
                  readable: bool, lifecycle_failed: bool) -> _HostCustody:
    """One inventory device, first match wins: a collection blind spot (every input) -> an unreadable register (no
    claim) -> no row (unavailable when the lifecycle phase that guarantees every device a row failed, else a
    contradiction with the producer: unverified) -> two rows naming it -> a row whose exposures cannot be indexed.
    The blind-spot answer is read only through the device scope's door (:meth:`_Ctx.device_scope`, F6): a scope that
    cannot say the device is not a blind spot makes its custody unverified for every input (``doubt``)."""
    scope = ctx.device_scope("collection_completeness", host)
    if scope is not None:
        where = json_pointer(*scope[2][0][1]) if scope[2] else json_pointer("collection_completeness", "devices")
        return ((_NC, where, "blind") if scope[0] == _NC else (_UV, where, "doubt")), None
    if not readable:
        return None, None
    row = ctx.cc_witness(host)             # the scope is not in doubt, so the owner's first-match row is the one
    own = json_pointer("devices", host) if host in dev_keys or not row else json_pointer(*row[0][1])
    rows = index.get(host, [])
    if not rows:
        return ((AU, own, "lost") if lifecycle_failed else (_UV, own, "unreadable")), None
    toks: Tuple[Any, ...] = ("device_dossiers", "per_device", rows[0])
    if len(rows) > 1:
        return (_UV, json_pointer(*toks), "unreadable"), None
    rec = raw[rows[0]]
    exposures = rec.get("exposures") if isinstance(rec, dict) else None
    if not isinstance(exposures, list):
        return (_UV, json_pointer(*toks), "unreadable"), None
    by_axis: Dict[str, List[int]] = {}
    for j, exposure in enumerate(exposures):
        axis = exposure.get("axis") if isinstance(exposure, dict) else None
        if not _is_text(axis):
            return (_UV, json_pointer(*toks, "exposures", j), "unreadable"), None
        by_axis.setdefault(axis, []).append(j)
    return None, (toks, exposures, by_axis)


def _axis_custody(axis: str, host: _HostCustody) -> Optional[Tuple[str, Optional[str], str, str]]:
    """``(custody, engine label, witness pointer, why)`` when `axis` did not assess the device, ``None`` when it did (or
    when nothing about the device can be read). Exactly one exposure must name the axis and pass the exposure record
    check; 'na' over published custody contradicts the producer's rule and is unverified."""
    fixed, joined = host
    if fixed is not None:
        return fixed[0], None, fixed[1], fixed[2]
    if joined is None:
        return None
    toks, exposures, by_axis = joined
    hits = by_axis.get(axis, [])
    if len(hits) != 1:
        return _UV, None, json_pointer(*toks, "exposures"), "unreadable"
    pointer = json_pointer(*toks, "exposures", hits[0])
    ok, rec = _typed(exposures[hits[0]], "exposure")
    if not ok:
        return _UV, None, pointer, "unreadable"
    if rec["state"] != "na":
        return None
    if rec["input_state"] == _PUB:
        return _UV, None, pointer, "unreadable"
    return rec["input_state"], rec["label"], pointer, "exposure"


def _trust_inputs(ctx: _Ctx) -> List[Dict[str, Any]]:
    """Per analysis input: the inventory devices it could not assess (``hosts``), their count (``n``) and the inventory
    count they are out of (``of``, the device rows' own reconciled total). A register row the host join cannot read
    (:func:`_unjoinable_rows`) makes ``hosts`` and ``n`` unverified, with a witness to each such row, while the readable
    rows' devices stay listed; ``of`` is the inventory's own owner and does not read the register."""
    hosts, dev_keys, _cc_norm = _inventory_universe(ctx)
    dd_toks = ("device_dossiers", "per_device")
    dd_state, dd_reason, dd_raw = _list_state(ctx, dd_toks, ("device_dossiers",))
    readable = dd_state in (_PUB, _CBE)
    index = ctx.index(dd_toks, ("host",)) if readable else {}
    # The join skips these rows, so the per-device fold never visits them: any could be a conflicting observation of
    # a listed device. Read as the strict selection reads them: over a published or empty register, and over an
    # unverified one whose rows can still be read.
    bad = ctx.unjoinable(dd_toks, ("host",)) if readable or (dd_state == _UV and isinstance(dd_raw, list)) else []
    unjoinable = _R_INPUTS_UNJOINABLE.format(n=len(bad), section=".".join(dd_toks)) if bad else None
    lifecycle_failed = ctx.abst("lifecycle_risk") == AU
    standing = [(host, _host_custody(ctx, host, dev_keys, index, dd_raw, readable, lifecycle_failed))
                for host in hosts]
    out: List[Dict[str, Any]] = []
    for axis, sections in TRUST_INPUTS.items():
        secs = tuple(dict.fromkeys(("device_dossiers",) + sections + ("collection_completeness",)))
        items: List[Dict[str, Any]] = []
        whys: List[str] = []
        for host, custody in standing:
            hit = _axis_custody(axis, custody)
            if hit is not None:
                items.append({"host": host, "custody": hit[0], "label": hit[1], "pointer": hit[2]})
                whys.append(hit[3])
        extra: List[Tuple[str, Sequence[Any]]] = [("basis", dd_toks),
                                                  ("basis", ("collection_completeness", "devices"))]
        extra += [("basis", (s,)) for s in secs if s != "device_dossiers"]
        lost = whys.count("lost")
        if lost:
            extra += [("basis", ("lifecycle_risk",))] + ctx.failure_entries(("lifecycle_risk",), True)
        failed = _secs_fail(ctx, ("device_dossiers.per_device",) + secs)
        doubt: Optional[str] = None
        if failed:
            state, reason = failed
        elif not readable:
            state, reason = dd_state, (_R_INPUTS_NO_REGISTER if dd_state == _NC else dd_reason)
            doubt = unjoinable                  # set only over an unverified register whose rows can be read
        elif not hosts:
            state, reason = _NC, _R_INPUTS_NO_DEVICE
        elif lost:
            state = AU
            reason = (ctx.unavailable_reason(("lifecycle_risk",)) + f"; {lost} device(s) have no risk-register "
                      "row, and the phase that guarantees every collected device one failed")
        elif "unreadable" in whys or "doubt" in whys:
            state, doubt = _UV, unjoinable
            parts = ([f"unverified: {whys.count('unreadable')} device(s) carry no single readable exposure for this "
                      "input in device_dossiers (a missing, duplicated or malformed row or record), so the count of "
                      "devices it could not assess is not verified"] if "unreadable" in whys else [])
            if "doubt" in whys:
                parts.append(_R_INPUTS_SCOPE.format(n=whys.count("doubt")))
            reason = "; ".join(parts)
        elif unjoinable is not None:
            state, reason, doubt = _UV, None, unjoinable
        else:
            state, reason = (_PUB, None) if items else (_CBE, _R_INPUTS_ASSESSED)
        if doubt is not None:
            # Never a published count or zero: the listed devices stay as data, each unreadable row is witnessed.
            state, reason = _UV, "; ".join(r for r in (reason, doubt) if r)
            extra += [("witness", dd_toks + (i,)) for i in bad]
        state, reason = _rolled(ctx, state, reason, secs, ("collection_completeness",))
        # W51: the blind-spot record's coverage verdict, for the gaps neither the rollup nor the inventory total reads;
        # its witnesses are cited whatever else withholds the list (a record doubt also doubts every device's custody)
        record = _roster_gaps(ctx)
        if record:
            extra += [entry for gap in record for entry in gap.entries()]
            if state in (_PUB, _CBE):
                state = impact_assessability.bound_state([(gap.state,) for gap in record])
                reason = _R_INPUTS_RECORD.format(word=impact_assessability.STATE_WORD[state],
                                                 clauses="; ".join(gap.clause for gap in record))
        of = _inventory_total(ctx, len(hosts))
        if state in (_PUB, _CBE) and of["state"] != _PUB:
            state, reason = of["state"], (f"{of['reason']}; the inventory denominator is withheld, so the device "
                                          "universe this list covers is not verified")
        listed = _listing(ctx, state, reason, None, _B_INPUTS, items, sections=secs, extra=extra,
                          caveats=("trust_inputs_scope",))
        refs = [dict(ref) for ref in listed["refs"]] + ctx.refs(
            [("denominator", ("collection_completeness", "summary", "inventory"))])
        if listed["state"] in (_PUB, _CBE):
            n = _envelope(_PUB, len(items), None, refs, _B_INPUTS + " (count)", "",
                          caveats=listed.get("caveats", ()))
        else:
            n = _envelope(listed["state"], None, None, refs, _B_INPUTS + " (count)", listed["reason"])
        out.append({"input": axis, "sections": list(sections), "n": n, "of": of, "hosts": listed})
    return out


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
        "inputs": _trust_inputs(ctx),
        "limitations": _limitations_payload(),
    }


def project_trust(snap: Any) -> Dict[str, Any]:
    """The Trust screen: census, failure record, coverage matrix, unknown evidence, SSOT verification and the
    analysis-input gap summary."""
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
    # G41: which exact byte string every pointer in this document resolves in. A value the owner computes from those
    # bytes, not from a snapshot address: no subject and no ref. Both facts share one state and one reason.
    state, sha, size, reason = ctx.source
    out["snapshot_sha256"] = _envelope(state, sha, None, [], f"{SNAPSHOT_IDENTITY_OWNER}:sha256", reason)
    out["snapshot_bytes"] = _envelope(state, size, None, [], f"{SNAPSHOT_IDENTITY_OWNER}:bytes", reason)
    out["snapshot_digest_form"] = SNAPSHOT_DIGEST_FORM
    return out


def project_engine(snap: Any) -> Dict[str, Any]:
    """Which snapshot schema and producer versions this payload was projected from, and (G41) which exact bytes:
    the SHA-256 and length its owner bound when a reader parsed them (:func:`protocol_assurance.bind_snapshot_json_bytes`),
    or not_collected for a snapshot handed over already parsed."""
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
    """One engine row joined for its cells: where it is, or why none of its fields can be read. A `bare` row (a
    forced page: an unknown or non-text host) names no snapshot location, so its cells cite no subject, basis or
    failure record; they cite only the row's own `extra` witnesses (:func:`_forced_wit`)."""
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


#: A forced device-page state (:func:`_roster_join`, :func:`_device_page`): ``(state, reason)``, or ``(state, reason,
#: witness ref entries)`` beside a roster row or list the host join cannot read. Its arity varies, so a reader takes
#: ``forced[0]`` and ``forced[1]`` and the witnesses only through :func:`_forced_wit`; it never unpacks the tuple.
_Forced = Tuple[Any, ...]


def _forced_wit(forced: Optional[_Forced]) -> List[Tuple[str, Sequence[Any]]]:
    """The witness ref entries a forced page carries: its optional third element, the roster rows or lists that leave
    an unknown host's absence open (:func:`_device_page`). ``(state, reason)`` alone carries none."""
    return list(forced[2]) if forced is not None and len(forced) > 2 else []


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
             absent: Optional[Tuple[str, str]] = None, forced: Optional[_Forced] = None,
             norm: bool = False) -> _Row:
    """Join one row. `path_toks` is a FIXED container path (never a host). With `key` alone the container is a
    map keyed by it; with `key_field` it is a list whose rows name the key in that field (with `norm`, compared
    without case or surrounding space); with neither the container itself is the row. First match wins: forced
    (an unknown device) -> the device's blind spot (owner order) -> a failed or faulted section -> an uncollected
    section -> a wrong container -> a device scope that cannot say the device is not a blind spot -> the join
    (unreadable / absent / ambiguous) -> a row of the wrong type.

    Every list join (`key_field`) is held to one rule: it reads one unique row or none from a list it can read in
    full. A row it cannot read (:func:`_unjoinable_rows`: not an object, or the key field missing or not text) could
    name this key, so with any such row in the list the join is unverified, with a witness to each such row and to
    each row that does name the key, whether one, several or none do: a row neither attaches silently nor vanishes.
    The device scope (`host`) is read only through :meth:`_Ctx.device_scope`, under the same rule."""
    keyed = key is not _MISSING and key_field is None
    cand: Optional[Tuple[Any, ...]] = (path_toks + (key,)) if keyed else (path_toks if key is _MISSING else None)
    if forced is not None:
        return _Row(forced[0], forced[1], None, None, sections, _forced_wit(forced), basis_refs=False, bare=True)
    scope = ctx.device_scope(sections[0], host) if host is not None else None
    if scope is not None and scope[0] == _NC:
        return _Row(_NC, scope[1], cand, None, sections, scope[2], basis_refs=False)
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
        if scope is not None:
            return _Row(scope[0], scope[1], cand, None, sections, scope[2], basis_refs=False)
        return _Row(None, None, path_toks, container, sections)
    need = dict if keyed else list
    if not isinstance(container, need):
        return _Row(_UV, f"unverified: {path} is not {_KIND[need]}, so no row can be read", cand, None, sections)
    if scope is not None:
        return _Row(scope[0], scope[1], cand, None, sections, scope[2], basis_refs=False)
    miss = absent or (_NC, _R_NO_ROW.format(section=path))
    if keyed:
        if not _is_text(key) or key not in container:
            return _Row(miss[0], miss[1], cand, None, sections)
        toks, raw = path_toks + (key,), container[key]
    else:
        idx = (ctx.index(path_toks, (key_field,), norm=norm).get(_norm(key) if norm else key, [])
               if _is_text(key) else [])
        lost = ctx.unjoinable(path_toks, (key_field,))
        if lost:
            doubts = ([_R_AMBIG.format(n=len(idx), section=path)] if len(idx) > 1 else []) + [
                _R_UNJOINABLE.format(n=len(lost), section=path)]
            return _Row(_UV, "; ".join(doubts), None, None, sections,
                        [("witness", path_toks + (i,)) for i in idx + lost])
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
        refs: List[Dict[str, str]] = ctx.refs(row.extra)        # a forced row's own witnesses only (_forced_wit)
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
    entries: List[Tuple[str, Sequence[Any]]] = list(extra)      # bare (a forced page): its own witnesses only
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
    missing -> it has no interface parse -> (with `config`) it has no security row. ``None``: nothing withheld.
    A device scope in doubt names no partial row here (:meth:`_Ctx.partial_row`); the caller carries that doubt."""
    if not _is_text(host):
        return None
    scope = ctx.device_scope(section, host)
    if scope is not None and scope[0] == _NC:
        return _R_DEVICE_BLIND, scope[2]
    i, row = ctx.partial_row(host)
    if i is not None and isinstance(row, dict):
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
               cbe: Union[str, Tuple[str, str]],
               unique: bool = False) -> Tuple[str, Optional[str], List[Tuple[str, Sequence[Any]]]]:
    """The state of the rows of one list that name a device: the owner's rows, or an honest absence. A device gap
    makes the selection not_collected: with rows it may be incomplete (with `unique`, the producer's one row for the
    device was computed without that evidence, so its values may be unreliable), without rows it is no clean result.
    `cbe` names what the producer looked for (an empty selection is collected_but_empty), or is the ``(state,
    reason)`` of an empty selection whose producer can never say "none" for a device (no row is not a clean result)."""
    if base not in (_PUB, _CBE):
        return base, reason, []
    if gap is not None:
        why, wit = gap
        if selected and unique:
            return _NC, (f"not collected: {why}. The producer writes one row per device, and it computed this "
                         "device's row without that evidence, so the row's values may be unreliable"), wit
        if selected:
            return _NC, (f"not collected: the list may be incomplete: {why}; the rows shown are the ones other "
                         "evidence names"), wit
        return _NC, (f"not collected: {why}, so no row naming it could be derived; an absent row is not a clean "
                     "result"), wit
    if selected:
        return _PUB, None, []
    if isinstance(cbe, tuple):
        return cbe[0], cbe[1], []
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


def _fleet_gap_reason(gap: "_CCGap") -> str:
    """How a fleet list words one gap of the blind-spot record's coverage verdict (:func:`_cc_coverage`)."""
    if gap.kind == _CC_UNREAD_ROWS:
        return _R_FLEET_UNREAD.format(n=len(gap.rows))
    if gap.kind == _CC_UNREADABLE:
        return _R_FLEET_UNREADABLE_LIST.format(path=".".join(gap.where[0]), kind=_KIND[gap.where[1]])
    return _R_FLEET_CC_GAP.format(clause=gap.clause)


def _fleet_qualify(ctx: _Ctx, config: bool = False) -> List[_Qualify]:
    """The fleet-list qualifications (see :data:`_Qualify`), read from the blind-spot record's one coverage verdict
    (:meth:`_Ctx.cc_coverage`): blind devices, then every gap that leaves the record unable to show each inventory
    device collected or listed -- a record the snapshot does not carry, a failed phase (its failure record always
    cited), a list or section that cannot be read (its owner reads it as listing none), rows that cannot be read as a
    blind spot (never passed over), and a summary that cannot be read or does not reconcile with the rows or the
    roster -- and, for the punch-list, devices whose running-config was not captured."""
    out: List[_Qualify] = []
    cov = ctx.cc_coverage()
    if cov.blind:
        out.append(("fleet_lists_exclude_blind_devices", _R_FLEET_BLIND.format(n=len(cov.blind)),
                    [("witness", ("collection_completeness", "devices", i)) for i in cov.blind]))
    for gap in cov.gaps:
        out.append(("fleet_lists_exclude_blind_devices", _fleet_gap_reason(gap), gap.entries()))
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


def _mg_pre(ctx: _Ctx, field: str = "wave", host: Any = None, *,
            subjects: Optional[Callable[[_Row], Any]] = None, include_unscheduled: bool = True) -> _Pre:
    """Validate a stored derived field's join to stored labels; never emit a repaired/positional value."""
    def pre(raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
        groups = ctx.s.get("move_groups")
        problem = _move_group_problem(groups)
        if problem:
            return problem
        rec = row.raw if isinstance(row.raw, dict) else {}
        if subjects is not None:
            hosts = subjects(row)
        elif host is not None:
            hosts = [host] if rec.get("device") == host else None
        else:
            hosts = rec.get("devices" if field == "wave" else "switches")
        invalid = (_UV, "unverified: this stored move-group value contradicts its devices' published group membership")
        if not _text_list(hosts)[0] or any(not h for h in hosts):
            return invalid
        labels = [g[MOVE_GROUP_LABEL] for g in groups if any(h in g["switches"] for h in hosts)]
        if field == "wave":
            known = {h for g in groups for h in g["switches"]}
            if include_unscheduled and any(h not in known for h in hosts) and MOVE_GROUP_UNSCHEDULED not in labels:
                labels.append(MOVE_GROUP_UNSCHEDULED)
            expected: Any = ", ".join(labels)
        elif field == "move_groups":
            expected = labels
        else:
            expected = len(labels) > 1
        if type(raw) is not type(expected) or raw != expected:
            return invalid
        return None
    return pre


def _move_group_problem(raw: Any) -> Optional[Tuple[str, str]]:
    """Validate stored identity, never invoke the engine's legacy positional-label fallback."""
    if raw is None:
        return _NC, "not collected: no move-group list was published"
    if not isinstance(raw, list):
        return _UV, "unverified: move_groups is not a list"
    labels: List[str] = []
    members: List[str] = []
    for group in raw:
        if (not isinstance(group, dict) or not isinstance(group.get("switches"), list)
                or not all(_is_text(h) and h.strip() for h in group["switches"])):
            return _UV, "unverified: a move-group row has malformed membership"
        members.extend(group["switches"])
        if MOVE_GROUP_LABEL in group:
            label = group[MOVE_GROUP_LABEL]
            if not _is_text(label) or not label.strip():
                return _UV, "unverified: a move-group label is not non-empty text"
            labels.append(label)
    if len(set(members)) != len(members):
        return _UV, "unverified: a device occurs more than once in the move-group membership"
    if raw and not labels:
        return _NC, _R_MG
    if len(labels) != len(raw) or len(set(labels)) != len(labels):
        return _UV, "unverified: move-group labels are incomplete or duplicated"
    return None


def _move_group_fact(ctx: _Ctx, host: Any, forced: Optional[_Forced] = None) -> Dict[str, Any]:
    source = _resolve(ctx, ("move_groups",), ("move_groups",), want=list, host=host, forced=forced)
    basis = "analyze.compute_move_groups:move_groups[].group"
    if source.state is not None:
        return _cell(ctx, source, None, "text", basis)
    problem = _move_group_problem(source.raw)
    if problem:
        row = _Row(problem[0], problem[1], source.toks, None, source.sections)
        return _cell(ctx, row, None, "text", basis,
                     caveats=("move_group_label_absent",) if problem[0] == _NC else ())
    matches = [(i, group) for i, group in enumerate(source.raw) if host in group["switches"]]
    if not matches:
        row = _Row(_CBE, "collected but empty: no published move group contains this device (not a blind spot)",
                   source.toks, None, source.sections)
        return _cell(ctx, row, None, "text", basis)
    index, group = matches[0]  # validated disjoint membership above; never an ambiguous first match
    row = _Row(None, None, ("move_groups", index), group, source.sections)
    return _cell(ctx, row, MOVE_GROUP_LABEL, "text", basis)


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


def _joins(ctx: _Ctx, host: Any, forced: Optional[_Forced] = None) -> Dict[str, _Row]:
    """The rows one device joins: its record, health, lifecycle, dossier and blind-spot rows. The blind-spot
    row itself is evidence of non-collection, so the device scope does not withhold it; it is joined by the rule
    of its owner's device scope (no case, no surrounding space). Its absence means "not a blind spot" only for a
    device the devices map carries, and only while every row of that list can be joined: each list join here follows
    the one rule of :func:`_resolve` (a row it cannot read, or a second row naming the device, makes it unverified)."""
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
    i = ctx.partial_row(host)[0]
    if i is not None:
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


def _capture_record(ctx: _Ctx, section: str, host: str) -> Tuple[Any, Any, Optional[str]]:
    """Exact capture-row custody; missing rows may fall back, malformed rows never do."""
    root = ctx.s.get(section, _MISSING)
    if root is _MISSING:
        return None, None, None
    if not isinstance(root, dict):
        return None, (section,), f"unverified: {section} capture owner is not a record"
    records = root.get("per_device", _MISSING)
    if records is _MISSING:
        return None, None, None
    if not isinstance(records, list):
        return None, (section, "per_device"), f"unverified: {section} capture rows are unreadable"
    selected = []
    for index, record in enumerate(records):
        name = record.get("host") if isinstance(record, dict) else None
        if not _is_text(name) or not name.strip():
            return None, (section, "per_device", index), f"unverified: {section} capture row has no readable host"
        if name == host:
            selected.append((record, (section, "per_device", index)))
    if len(selected) > 1:
        return None, (section, "per_device"), f"unverified: multiple {section} capture rows name this exact host"
    return (*selected[0], None) if selected else (None, None, None)


def _device_finding_rollup(ctx: _Ctx, host: Any,
                           forced: Optional[_Forced] = None) -> Dict[str, Any]:
    """Publish the pure owner fold only after scoped input and positive capture custody."""
    sections = ("punchlist",) + PUNCHLIST_INPUTS
    base, reason, _raw = _list_state(ctx, ("punchlist",), ("punchlist",))
    state, reason = _rolled(ctx, base, reason, ("punchlist",), PUNCHLIST_INPUTS)
    witness: List[Tuple[str, Sequence[Any]]] = [("basis", ("punchlist",))]
    values: Dict[str, Any] = {"worst": None, "by_severity": None}
    if forced is not None:
        # a forced state is ``(state, reason)`` or, beside a roster it cannot read, ``(state, reason, witnesses)``
        # (:func:`_roster_join`); its witnesses ride in the row's extra (:func:`_forced_wit`), never in the unpacking
        state, reason = forced[0], forced[1]
    elif not _is_text(host) or not host.strip():
        state, reason = _UV, "unverified: no exact device identity selects this finding rollup"
    elif state in (_PUB, _CBE):
        scope = ctx.device_scope("punchlist", host)
        gap = _device_gap(ctx, host, "punchlist", SELECTION_NEEDS["findings"], config=True)
        if scope is not None and scope[0] == _UV:
            # unverified wins over a capture gap (as in _selection_rows); the gap is carried beside it
            state, reason = _UV, scope[1] + (f"; the device also has a collection gap: {gap[0]}" if gap else "")
            witness += scope[2] + (gap[1] if gap else [])
        elif gap is not None:
            why, extra = gap
            state, reason = _NC, f"not collected: finding counts may be incomplete: {why}"
            witness += extra
        else:
            software, sw_toks, problem = _capture_record(ctx, "software_risk", host)
            qos, qa_toks = None, None
            if problem is None and software is None:
                qos, qa_toks, problem = _capture_record(ctx, "qos_audit", host)
            if sw_toks is not None:
                witness.append(("witness", sw_toks))
            if qa_toks is not None:
                witness.append(("witness", qa_toks))
            capture = device_config_capture(software, qos) if problem is None else None
            security = _get(ctx.s, ("security", host))
            if problem is not None:
                state, reason = _UV, problem
            elif capture is False:
                state, reason = _NC, "not collected: the canonical capture owner reports no running-config"
            elif capture is not True:
                state, reason = _UV, "unverified: running-config capture custody is missing or not an exact boolean"
            elif not isinstance(security, dict) or not security:
                state, reason = _UV, "unverified: the captured running-config has no readable security assessment"
                witness.append(("witness", ("security", host)))
            else:
                folded = ctx.device_findings
                partition = folded.get("per_device") if isinstance(folded, dict) else None
                result = partition.get(host) if isinstance(partition, dict) else None
                problem = folded.get("problem") if isinstance(folded, dict) else "unreadable owner output"
                if problem is not None or not isinstance(result, dict):
                    state, reason = _UV, f"unverified: the engine finding partition is unavailable ({problem or 'no scoped host'})"
                else:
                    indices = result.get("indices")
                    if (not isinstance(indices, list) or not isinstance(_raw, list)
                            or any(type(index) is not int or not 0 <= index < len(_raw) for index in indices)):
                        state, reason = _UV, "unverified: the engine finding partition has unreadable source indices"
                    else:
                        values = result
                        witness += [("witness", ("punchlist", index)) for index in indices]
    held = None if state in (_PUB, _CBE) else state
    row = _Row(held, reason, None, values, sections, _forced_wit(forced), basis_refs=forced is None,
               bare=forced is not None)

    def empty_worst(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
        return (_CBE, "collected but empty: no stored punch-list finding names this captured device; not a clean bill of health") \
            if raw is None else None

    basis = "analyze.compute_device_findings:stored punch-list rows by exact device."
    return {
        "worst": _cell(ctx, row, "worst", "enum", basis + "worst", vocab=SEVERITIES, pre=empty_worst,
                       witness=witness, published_caveats=("device_findings_scope",)),
        "by_severity": _cell(ctx, row, "by_severity", "severity_counts", basis + "by_severity",
                             witness=witness, published_caveats=("device_findings_scope",)),
    }


def _coverage_scope(ctx: _Ctx, host: Any, forced: Optional[_Forced] = None) -> _Row:
    return _resolve(ctx, ("coverage_matrix", "by_device"), ("coverage_matrix",), key=host,
                    host=host, forced=forced,
                    absent=(_NC, "not collected: coverage_matrix carries no row for this device"))


def _coverage_join(ctx: _Ctx, cov: _Row, host: str, axis: str) -> _Row:
    """Metadata and the displayed cell admit the same unique, exact owner row."""
    extra: List[Tuple[str, Sequence[Any]]] = [
        ("basis", ("coverage_matrix", "rows")), ("witness", cov.toks + (axis,)),
    ] if cov.toks is not None else []
    index = ctx.coverage_rows
    matched = None
    if index is not None:
        extra += [("witness", ("coverage_matrix", "rows", i)) for i, _raw in index.by_key.get((host, axis), ())]
        extra += [("witness", ("coverage_matrix", "rows", i)) for i in index.unreadable_indices]
        try:
            matched = match_coverage_cell(index, host, axis, cov.raw[axis])
        except _OWNER_FAULTS as exc:
            ctx.faults["coverage_matrix.match_coverage_cell"] = _fault_text("coverage_matrix.match_coverage_cell", exc)
    if matched is None:
        return _Row(_UV, "unverified: no unique, consistent coverage row joins this exact device and axis",
                    None, None, ("coverage_matrix",), extra)
    i, raw = matched
    return _Row(None, None, ("coverage_matrix", "rows", i), raw, ("coverage_matrix",), extra)


def _device_coverage_rollup(ctx: _Ctx, host: Any,
                            forced: Optional[_Forced] = None) -> Dict[str, Any]:
    """The complete stored axis fold, with no zero/all-covered assurance from silent sources."""
    cov = _coverage_scope(ctx, host, forced)
    state, reason = cov.state, cov.reason
    values: Dict[str, Any] = {}
    witness: List[Tuple[str, Sequence[Any]]] = []
    if not cov.bare:
        witness = [("basis", ("coverage_matrix", "rows")), ("basis", ("coverage_matrix", "by_device"))]
        if cov.toks is not None:
            witness.append(("witness", cov.toks))
    if state is None:
        if not cov.raw:
            state, reason = _NC, "not collected: no device coverage axes were retained; absence is not zero abstentions"
        else:
            folded = ctx.coverage_for(host)
            if not isinstance(folded, dict):
                state, reason = _UV, "unverified: the device coverage axis set cannot be joined uniquely and consistently"
            else:
                indices = folded.get("row_indices")
                rows = _get(ctx.s, ("coverage_matrix", "rows"))
                if (not isinstance(indices, list) or not isinstance(rows, list)
                        or any(type(i) is not int or not 0 <= i < len(rows) for i in indices)):
                    state, reason = _UV, "unverified: the device coverage fold has unreadable source indices"
                else:
                    witness += [("witness", ("coverage_matrix", "rows", i)) for i in indices]
                    if folded.get("worst") == "covered" or folded.get("n_abstained") == 0:
                        state, reason = _UV, ("unverified: covered rows may come from silent coverage sources, so zero "
                                              "abstentions and an all-covered device are not verified")
                    else:
                        values = folded
    row = _Row(state, reason, None, values, ("coverage_matrix",), cov.extra,
               basis_refs=not cov.bare, bare=cov.bare)
    basis = "coverage_matrix.compute_device_coverage:stored matrix rows by exact device."
    return {
        "worst": _cell(ctx, row, "worst", "enum", basis + "worst", vocab=COVERAGE_STATE_ORDER,
                       witness=witness, caveats=("coverage_matrix_shown_as_published",)),
        "n_abstained": _cell(ctx, row, "n_abstained", "count", basis + "n_abstained",
                             witness=witness, caveats=("coverage_matrix_shown_as_published",)),
    }


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
        "move_group": _move_group_fact(ctx, host),
        "findings": _device_finding_rollup(ctx, host),
        "coverage": _device_coverage_rollup(ctx, host),
    }
    for field in ("model", "platform", "sw_version", "serial_number"):
        row[field] = _cell(ctx, j["devices"], field, "text", _dev_basis(field), pre=_default_text)
    row.update(role=health["role"], health_score=health["score"], health_band=health["band"],
               lifecycle_band=_cell(ctx, j["lifecycle"], "band", "enum", _B_LIFECYCLE + "band",
                                    vocab=LIFECYCLE_BAND_ORDER),
               risk_band=_risk_band(ctx, j["dossier"]))
    return row


def _cc_universe(ctx: _Ctx) -> Tuple[Dict[str, List[int]], Any, List[int], Optional[Tuple[Tuple[str, ...], type]],
                                      List[Tuple[str, Sequence[Any]]]]:
    """``(index, rows, lost rows, unreadable list, witnesses)``: the blind-spot list as the inventory universe reads it,
    in one place, under the one key-join rule (F6). Its exact-key index by the owner's device-scope rule (the name
    without case or surrounding space), the list itself, the rows that join cannot read, where the list itself cannot
    be read (:meth:`_Ctx.cc_unreadable`), and a witness to each of those. A row the host join cannot read names a
    device this universe cannot list, and a list (or section) carried as the wrong type hides every row it holds the
    same way: both are disclosed with a witness, never dropped."""
    index = ctx.index(_CC_ROWS, ("host",), norm=True)
    lost = ctx.unjoinable(_CC_ROWS, ("host",))
    unreadable = ctx.cc_unreadable()
    wit: List[Tuple[str, Sequence[Any]]] = [("witness", _CC_ROWS + (i,)) for i in lost] + (
        [("witness", unreadable[0])] if unreadable is not None else [])
    return index, _get(ctx.s, _CC_ROWS), lost, unreadable, wit


def _inventory_universe(ctx: _Ctx) -> Tuple[List[str], FrozenSet[str], Dict[str, List[int]]]:
    """``(hosts, devices-map keys, blind-spot index)``: the inventory roster, sorted. It is the devices map's text
    keys plus the collection_completeness blind spots it does not name (:func:`_cc_universe`, whose rows and list it
    cannot read the roster list and the inventory count disclose). One owner for the inventory device rows, the
    analysis-input gaps (G08) and the device finding facet (G21), so all three count the same universe."""
    devices = ctx.s.get("devices")
    dev_keys = frozenset(k for k in devices if _is_text(k)) if isinstance(devices, dict) else frozenset()
    cc_norm, cc_rows, _lost, _unreadable, _wit = _cc_universe(ctx)
    dev_norm = {_norm(k) for k in dev_keys}
    # a blind spot the devices map names (without case or surrounding space) is that device's row, not a new one;
    # the rest are named by their first row's own spelling
    blind_only = {cc_rows[idx[0]]["host"] for name, idx in cc_norm.items() if name not in dev_norm}
    return sorted(dev_keys | blind_only), dev_keys, cc_norm


def _inventory_reconcile(ctx: _Ctx, typed: Any, n_rows: int) -> Optional[Tuple[str, str, List[Tuple[str, Sequence[Any]]]]]:
    """The one rule the owner's inventory count is held to (the inventory rows' total, :func:`_inventory_total`, and
    the blind-spot record's coverage verdict, :func:`_cc_coverage`, both read it here): ``None`` when the count equals
    the inventory rows' count; otherwise why not, as an unverified gate result. While the blind-spot list holds a row
    or value the universe cannot read (:func:`_cc_universe`), the two cannot be reconciled at all."""
    _index, _rows, lost, unreadable, lost_wit = _cc_universe(ctx)
    if unreadable is not None:
        return (_UV, f"unverified: {'.'.join(unreadable[0])} is present but is not {_KIND[unreadable[1]]}, so the "
                     f"inventory rows cannot be reconciled with the owner's inventory count", list(lost_wit))
    if lost:
        return (_UV, f"unverified: {len(lost)} collection_completeness row(s) cannot be joined by host, so the "
                     f"inventory rows cannot be reconciled with the owner's inventory count", list(lost_wit))
    if typed == n_rows:
        return None
    return (_UV, f"unverified: the inventory rows (the devices map and the collection_completeness blind spots) "
                 f"number {n_rows}; the owner's inventory count says {typed}", [])


def _inventory_total(ctx: _Ctx, n_rows: int) -> Dict[str, Any]:
    """The owner's inventory count, published only when it equals the inventory rows' count, and never while the
    blind-spot list holds a row or value the universe cannot read (:func:`_inventory_reconcile`)."""
    def _matches_rows(_ctx: _Ctx, typed: Any, _zero: bool):
        return _inventory_reconcile(ctx, typed, n_rows)

    return _scalar(ctx, "collection_completeness.summary.inventory", "count",
                   "analyze.compute_collection_completeness:collection_completeness.summary.inventory",
                   gate=_matches_rows, witness=[("witness", ("executive_brief", "scale", "n_devices")),
                                                ("witness", ("coverage_matrix", "summary", "n_devices"))],
                   published_caveats=_brief_caveats(ctx))


# ---------------------------------------------------------------------------------------------------
# the blind-spot record's one coverage verdict (W51 second round)
# ---------------------------------------------------------------------------------------------------
#: The record shows every inventory device collected or listed (no gap, no listed blind spot) ...
_CC_COMPLETE = "complete"
#: ... or it lists blind spots and nothing leaves that list in doubt.
_CC_INCOMPLETE = "incomplete"
#: The gap kinds of :func:`_cc_coverage`. At most one of the first four (the record cannot be read as a list at all);
#: the rest are found only in a list that can be read.
_CC_FAILED, _CC_FAULTED, _CC_UNREADABLE, _CC_ABSENT = "failed", "faulted", "unreadable", "absent"
_CC_UNREAD_ROWS, _CC_SUMMARY_UNREAD, _CC_SUMMARY_UNLISTED, _CC_INVENTORY = (
    "unread_rows", "summary_unread", "summary_unlisted", "inventory")
#: The gaps that leave the record itself untrusted for EVERY device (failed, faulted, unreadable, or its own summary
#: counting a blind spot the list does not carry): the device scope's doubt (:meth:`_Ctx.scope_doubt`) reads exactly
#: these. A record the snapshot does not carry is the collection row's own not_collected; rows that cannot be read are
#: doubted per device by the scope's own row rules; and the inventory count is a statement about the roster, which
#: only the fleet-level readers count over.
_CC_RECORD_DOUBTS: FrozenSet[str] = frozenset({_CC_FAILED, _CC_FAULTED, _CC_UNREADABLE, _CC_SUMMARY_UNREAD,
                                              _CC_SUMMARY_UNLISTED})


class _CCGap:
    """One reason the blind-spot record cannot show every inventory device collected or listed. ``clause`` states it
    without a state word; ``witness`` are the ref entries showing it (a reader may cap them); ``failure`` are the
    failure-record entries of a failed phase, which every reader cites in full, never capped; ``rows`` the row indices
    of an unread-rows gap; ``where`` the ``(path, type)`` of an unreadable record, or, for an absent one, what is not
    carried: the list (inside a section the snapshot carries) or the section itself."""
    __slots__ = ("kind", "state", "clause", "witness", "failure", "rows", "where")

    def __init__(self, kind: str, state: str, clause: str, witness: Sequence[Tuple[str, Sequence[Any]]],
                 failure: Sequence[Tuple[str, Sequence[Any]]] = (), rows: Sequence[int] = (),
                 where: Any = None) -> None:
        self.kind, self.state, self.clause = kind, state, clause
        self.witness: Tuple[Tuple[str, Sequence[Any]], ...] = tuple(witness)
        self.failure: Tuple[Tuple[str, Sequence[Any]], ...] = tuple(failure)
        self.rows: Tuple[int, ...] = tuple(rows)
        self.where = where

    def entries(self, cap: Optional[int] = None) -> List[Tuple[str, Sequence[Any]]]:
        """Its witnesses (the first `cap` of them), then every failure record."""
        return list(self.witness if cap is None else self.witness[:cap]) + list(self.failure)


class _CCCoverage:
    """:func:`_cc_coverage`'s verdict: ``state`` is :data:`_CC_COMPLETE`, :data:`_CC_INCOMPLETE`, or the strongest gap
    state (analysis_unavailable, then unverified, then not_collected); ``blind`` the readable blind-spot rows; ``gaps``
    every :class:`_CCGap`, in the order found."""
    __slots__ = ("state", "blind", "gaps")

    def __init__(self, blind: Sequence[int], gaps: Sequence[_CCGap]) -> None:
        self.blind: Tuple[int, ...] = tuple(blind)
        self.gaps: Tuple[_CCGap, ...] = tuple(gaps)
        self.state = (impact_assessability.bound_state([(gap.state,) for gap in self.gaps]) if self.gaps
                      else _CC_INCOMPLETE if self.blind else _CC_COMPLETE)


def _cc_coverage(ctx: _Ctx) -> _CCCoverage:
    """Whether collection_completeness shows every inventory device collected or listed: the one verdict every reader
    of the collection's blind spots takes (:meth:`_Ctx.cc_coverage`: the fleet qualifier, the device scope's doubt, the
    gateway and address coverage, the axis denominators, the trust inputs and the inventory rows). The record is never
    trusted by default; first match wins for the record itself:

    * its phase failed (the abstention core's analysis_unavailable): ``failed``, analysis_unavailable, citing every
      failure record, whatever the fallback holds;
    * an owner fault: ``faulted``, unverified;
    * the list, or its section, carried as the wrong type (the owner reads it as listing none): ``unreadable``;
    * the section or the list not carried (missing or null): ``absent``, not_collected -- no blind spot can be ruled
      out, so it is never "no blind spot";

    and, over a list that can be read, every one of: rows that cannot be read as a blind spot (``unread_rows``); a
    summary that is not an object or whose partial, not_collected or inventory count is not a count
    (``summary_unread``); a summary counting more partial and not-collected devices than the list carries
    (``summary_unlisted``: the producer writes one row per such device, so one may be missing); and, over a readable
    devices map and a list every row of which the host join can read, an inventory count other than the inventory
    rows' count, by the one rule the inventory total applies (:func:`_inventory_reconcile`; ``inventory``). A list
    carrying MORE such rows than its summary counts over-reports, so it hides no blind spot and is no gap."""
    section = ctx.s.get("collection_completeness")
    where = _CC_ROWS if isinstance(section, dict) and "devices" in section else ("collection_completeness",)
    hit = _secs_fail(ctx, (".".join(_CC_ROWS), "collection_completeness"))
    if hit is not None:
        if hit[0] == AU:
            return _CCCoverage((), [_CCGap(_CC_FAILED, AU, _R_CC_UNREAD.format(why=hit[1]), [("witness", where)],
                                           ctx.failure_entries(("collection_completeness",), True))])
        return _CCCoverage((), [_CCGap(_CC_FAULTED, _UV, _R_CC_UNREAD.format(why=hit[1]), [("witness", where)])])
    unreadable = ctx.cc_unreadable()
    if unreadable is not None:
        why = f"unverified: {'.'.join(unreadable[0])} is present but is not {_KIND[unreadable[1]]}"
        return _CCCoverage((), [_CCGap(_CC_UNREADABLE, _UV, _R_CC_UNREAD.format(why=why), [("witness", unreadable[0])],
                                       where=unreadable)])
    state, reason, rows = _list_state(ctx, _CC_ROWS, ("collection_completeness",))
    if not isinstance(rows, list):
        kind = _CC_ABSENT if state == _NC else _CC_FAULTED
        # `where` of an absent record: the list when its section is carried (the section rollup reads that as present)
        absent_at = _CC_ROWS if isinstance(section, dict) else ("collection_completeness",)
        return _CCCoverage((), [_CCGap(kind, _NC if state == _NC else _UV, _R_CC_UNREAD.format(why=reason or _R_NC),
                                       [("witness", where)], where=absent_at)])
    blind = ctx.blind_rows()
    gaps: List[_CCGap] = []
    unread = ctx.unread_blind_rows()
    if unread:
        gaps.append(_CCGap(_CC_UNREAD_ROWS, _UV, _R_CC_ROWS.format(k=len(unread)),
                           [("witness", ("collection_completeness", "devices", i)) for i in unread], rows=unread))
    stoks = ("collection_completeness", "summary")
    summary = _get(ctx.s, stoks)
    if summary is not _MISSING and summary is not None and not isinstance(summary, dict):
        gaps.append(_CCGap(_CC_SUMMARY_UNREAD, _UV, _R_CC_SUMMARY_UNREAD, [("witness", stoks)]))
    elif isinstance(summary, dict):
        # analyze.compute_collection_completeness counts each blind-spot status under that status's own summary key
        # (its space written '_'), and lists one devices row per such device
        keys = tuple(status.replace(" ", "_") for status in CC_STATUSES)
        if any(key in summary for key in keys):
            counts = [_count(summary.get(key, 0)) for key in keys]
            if not all(ok for ok, _n in counts):
                gaps.append(_CCGap(_CC_SUMMARY_UNREAD, _UV, _R_CC_SUMMARY_UNREAD, [("witness", stoks)]))
            elif sum(n for _ok, n in counts) > len(blind):
                gaps.append(_CCGap(_CC_SUMMARY_UNLISTED, _UV,
                                   _R_CC_SUMMARY.format(k=sum(n for _ok, n in counts), n=len(blind)),
                                   [("witness", stoks)]))
        if "inventory" in summary:
            ok, typed = _count(summary["inventory"])
            if not ok:
                gaps.append(_CCGap(_CC_SUMMARY_UNREAD, _UV, _R_CC_INVENTORY_UNREAD, [("witness", stoks + ("inventory",))]))
            elif isinstance(ctx.s.get("devices"), dict) and not _cc_universe(ctx)[2]:
                n_rows = len(_inventory_universe(ctx)[0])
                if _inventory_reconcile(ctx, typed, n_rows) is not None:
                    gaps.append(_CCGap(_CC_INVENTORY, _UV, _R_CC_INVENTORY.format(typed=typed, n=n_rows),
                                       [("witness", stoks + ("inventory",))]))
    return _CCCoverage(blind, gaps)


#: The coverage gaps the inventory rows and the trust inputs take from the record's verdict themselves: the ones their
#: own section rollup (an absent section, a failed phase) and the inventory total (an unreadable list, an inventory
#: count off the roster) do not already report. An absent list inside a present section is the rollup's blind spot.
_CC_ROSTER_GAPS: FrozenSet[str] = frozenset({_CC_SUMMARY_UNREAD, _CC_SUMMARY_UNLISTED})


def _roster_gaps(ctx: _Ctx) -> List[_CCGap]:
    """The record gaps a roster-derived list must take itself (:data:`_CC_ROSTER_GAPS`, and a devices list absent
    from a section the snapshot does carry, which the section rollup reads as present)."""
    return [gap for gap in ctx.cc_coverage().gaps
            if gap.kind in _CC_ROSTER_GAPS or (gap.kind == _CC_ABSENT and gap.where == _CC_ROWS)]


def _roster_list(ctx: _Ctx, items: List[Any], basis: str, caveats: Sequence[str]) -> Dict[str, Any]:
    """A list with one item per :func:`_inventory_universe` host, in the roster's own state: the devices map's state,
    then the collection_completeness rollup. An absent or unreadable devices map is never an empty roster, and (F6) a
    blind-spot row or list the universe cannot read makes it unverified with a witness; so does (W51) a record whose
    summary counts a blind spot its list does not carry, or whose list is absent from its section
    (:func:`_roster_gaps`). The inventory rows and the device finding facet share this one state."""
    base, reason, _raw = _list_state(ctx, ("devices",), ("devices",), want=dict)
    if base in (_PUB, _CBE):
        base = _PUB if items else _CBE
    # F6: a blind-spot row the host join cannot read, or a blind-spot list it cannot read, may hide a roster device
    _index, _rows, lost, unreadable, lost_wit = _cc_universe(ctx)
    extra = list(lost_wit)
    if lost_wit and base in (_PUB, _CBE):
        base, reason = _UV, (_R_INVENTORY_UNJOINABLE.format(n=len(lost)) if unreadable is None else
                             _R_INVENTORY_UNREADABLE.format(path=".".join(unreadable[0]), kind=_KIND[unreadable[1]]))
    held = _roster_gaps(ctx)
    extra += [entry for gap in held for entry in gap.entries()]
    if held and base in (_PUB, _CBE):
        base = impact_assessability.bound_state([(gap.state,) for gap in held])
        reason = _R_INVENTORY_RECORD.format(word=impact_assessability.STATE_WORD[base],
                                            clauses="; ".join(gap.clause for gap in held))
    return _listing(ctx, base, reason, ("devices",), basis, items, sections=("devices",),
                    rollup=("collection_completeness",), extra=extra, caveats=caveats)


def _device_rows(ctx: _Ctx) -> Dict[str, Any]:
    hosts, dev_keys, cc_norm = _inventory_universe(ctx)
    items = [_device_row(ctx, host, dev_keys, cc_norm) for host in hosts]
    rows = _roster_list(ctx, items, "html.snapshot_state:devices + analyze.compute_collection_completeness:"
                                    "collection_completeness.devices",
                        ("row_selection_by_exact_key", "device_physical_defaults_not_observed"))
    return {"total": _inventory_total(ctx, len(items)), "rows": rows}


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


def _signed_safe_int(value: Any) -> bool:
    return type(value) is int and -JS_MAX_SAFE_INT <= value <= JS_MAX_SAFE_INT


def _stp_identities(raw: Any) -> Tuple[bool, Any]:
    """Typed copies of the owner's identities, including unknown and conflicting priorities."""
    if not isinstance(raw, list):
        return False, None
    out = []
    keys = {"root_address", "root_priority", "root_priorities", "claimants", "observers"}
    for identity in raw:
        if not isinstance(identity, dict) or set(identity) != keys or not _is_text(identity["root_address"]):
            return False, None
        priority, priorities = identity["root_priority"], identity["root_priorities"]
        if (not isinstance(priorities, list) or not all(_signed_safe_int(p) for p in priorities)
                or priorities != sorted(set(priorities))
                or (priority is not None and not _signed_safe_int(priority))
                or priority != (priorities[0] if len(priorities) == 1 else None)):
            return False, None
        for field in ("claimants", "observers"):
            if not _text_list(identity[field])[0] or any(not h for h in identity[field]):
                return False, None
        out.append({"root_address": identity["root_address"], "root_priority": priority,
                    "root_priorities": list(priorities), "claimants": list(identity["claimants"]),
                    "observers": list(identity["observers"])})
    return True, out


def _stp_contract(row: _Row) -> Optional[Tuple[str, str]]:
    """Check the published record's contract, never derive an election from stp_roots."""
    rec = row.raw if isinstance(row.raw, dict) else {}
    fields = ("stp_root_state", "stp_root_reason", "stp_root_claimants", "stp_root_identities")
    if not any(field in rec for field in fields):
        return _NC, "not collected: this legacy VLAN row publishes no STP election verdict; uniqueness is unknown"
    state, reason = rec.get("stp_root_state"), rec.get("stp_root_reason")
    claimants = rec.get("stp_root_claimants")
    ok, identities = _stp_identities(rec.get("stp_root_identities"))
    malformed = (_UV, "unverified: the published STP election fields are malformed or contradict each other")
    if (not _is_text(state) or state not in STP_ROOT_ELECTION_STATES
            or not _is_text(reason) or reason not in STP_ROOT_ELECTION_REASONS[state]
            or not _text_list(claimants)[0] or any(not h for h in claimants) or not ok):
        return malformed
    root, default = rec.get("stp_root"), rec.get("stp_root_default_election", _MISSING)
    if state == _PUB:
        if (len(claimants) != 1 or not _is_text(root) or root != claimants[0]
                or len(identities) != 1 or identities[0]["claimants"] != claimants
                or (default is not None and not isinstance(default, bool))
                or (default is None) != (identities[0]["root_priority"] is None)):
            return malformed
        priority = identities[0]["root_priority"]
        vlan = rec.get("vlan")
        if (priority is not None and (type(vlan) is not int or not 0 <= vlan <= JS_MAX_SAFE_INT
                or default is not (priority in (STP_DEFAULT_BRIDGE_PRIORITY, STP_DEFAULT_BRIDGE_PRIORITY + vlan)))):
            return malformed
    elif root != (AMBIGUOUS_STP_SENTINEL if state == "ambiguous" else NOT_OBSERVED_SENTINEL) or default is not None:
        return malformed
    elif state == "not_observed" and (claimants or len(identities) > 1
                                      or (reason == "no_root_evidence") != (not identities)):
        return malformed
    elif reason == "multiple_root_identities" and len(identities) < 2:
        return malformed
    elif reason == "duplicate_bridge_identity" and (len(claimants) < 2 or len(identities) != 1):
        return malformed
    if sorted(h for identity in identities for h in identity["claimants"]) != sorted(claimants):
        return malformed
    return None


def _stp_metadata_pre(_raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    return _stp_contract(row)


def _stp_verdict_pre(raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    problem = _stp_contract(row)
    if problem:
        return problem
    state = row.raw["stp_root_state"]
    if state == "ambiguous":
        return _UV, "unverified: the engine reports an ambiguous STP election: " + row.raw["stp_root_reason"]
    if state == "not_observed":
        return _NC, "not collected: the engine reports no observed STP root: " + row.raw["stp_root_reason"]
    if raw is None:
        return _NC, "not collected: the engine withholds default election because the root priority is undetermined"
    return None


def _vlan_readiness_pre(raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    if raw == "":
        return _NC, "not collected: no readiness verdict covers this VLAN's move groups"
    if raw == "READY":
        problem = _stp_contract(row)
        if problem and problem[0] == _UV:
            return _UV, "unverified: READY accompanies malformed or contradictory published STP election fields"
    return None


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
        "stp_root": ("text", (), _stp_verdict_pre, None, ()),
        "stp_root_default_election": ("flag", (), _stp_verdict_pre, None, ()),
        "stp_root_state": ("enum", STP_ROOT_ELECTION_STATES, _stp_metadata_pre, None, ()),
        "stp_root_reason": ("enum", STP_ROOT_REASONS, _stp_metadata_pre, None, ()),
        "stp_root_claimants": ("text_list", (), _stp_metadata_pre,
                              (_CBE, "collected but empty: the published STP claimant list contains no parsed entries; "
                               "consult election state/reason for ownership"), ()),
        "stp_root_identities": ("stp_identities", (), _stp_metadata_pre,
                               (_CBE, "collected but empty: the published STP identity list contains no parsed entries; "
                                "consult election state/reason for ownership"), ()),
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
        "readiness": ("enum", VLAN_READINESS, _vlan_readiness_pre, None, ("vlan_readiness_scope",)),
        "cutover_window": ("text", (), _blank(_R_HUMAN), None, ()),
        "rollback_owner": ("text", (), _blank(_R_HUMAN), None, ()),
    })


def _stp_vlan_key(value: Any) -> Optional[int]:
    """Selection-only copy of stp_topology._election_priority's nonnegative key rule, parity pinned by tests."""
    if type(value) is int:
        return value if 0 <= value <= JS_MAX_SAFE_INT else None
    if _is_text(value):
        token = value.strip()
        if len(token) <= 16 and token.isascii() and token.isdigit():
            number = int(token)
            return number if number <= JS_MAX_SAFE_INT else None
    return None


def _stp_root_index(ctx: _Ctx) -> Dict[int, List[Tuple[str, Any, Any]]]:
    """VLAN id -> stored host/key/record, retaining aliases and the owner's non-MST selection rule."""
    out: Dict[int, List[Tuple[str, Any, Any]]] = {}
    roots = ctx.s.get("stp_roots")
    for host in sorted(k for k in roots if _is_text(k) and k) if isinstance(roots, dict) else ():
        recs = roots[host]
        for key in recs if isinstance(recs, dict) else ():
            vid = _stp_vlan_key(key)
            if vid is not None and not (isinstance(recs[key], dict) and recs[key].get("is_mst")):
                out.setdefault(vid, []).append((host, key, recs[key]))
    return {vid: sorted(rows, key=lambda row: json_pointer("stp_roots", row[0], row[1]))
            for vid, rows in out.items()}


def _stp_observed_flag(raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    if type(raw) is not bool:
        return _UV, "unverified: the stored STP is_root flag is not a boolean"
    if raw is False:
        address = row.raw.get("root_address", _MISSING)
        if address is _MISSING or (_is_text(address) and not address.strip()):
            return _NC, ("not collected: the root address was not parsed; False is the spanning-tree parser's "
                         "default here, not an observed non-root result")
        if not _is_text(address):
            return _UV, "unverified: the stored root address cannot qualify the parser's False flag"
    return None


def _stp_observed_address(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    if _is_text(raw) and not raw.strip():
        return _NC, "not collected: the spanning-tree root address was not parsed"
    return None


def _stp_observed_priority(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, "not collected: the spanning-tree root priority was not parsed") if raw is None else None


def _stp_observation(ctx: _Ctx, host: str, key: Any, raw: Any) -> Dict[str, Any]:
    toks = ("stp_roots", host, key)
    held = _secs_fail(ctx, ("stp_roots",))
    extra = []
    # W51 (F6 x G15): the device scope is read only through its doubt-aware door: a blind spot is not collected, and
    # a scope that cannot say this device is not a blind spot leaves its observation unverified, with the witnesses
    scope = ctx.device_scope("stp_roots", host) if held is None else None
    if scope is not None:
        held, extra = (scope[0], scope[1]), list(scope[2])
    if held is None and isinstance(raw, dict) and "is_mst" in raw and type(raw["is_mst"]) is not bool:
        held = (_UV, "unverified: the stored STP namespace marker is not a boolean; this may be an MST instance")
        extra = [("witness", toks + ("is_mst",))]
    row = (_Row(*held, toks, raw, ("stp_roots",), extra) if held is not None
           else _list_row(toks, raw, ("stp_roots",)))
    out: Dict[str, Any] = {"host": host, "pointer": json_pointer(*toks)}
    for field, slot, pre in (("is_root", "flag", _stp_observed_flag),
                              ("root_address", "text", _stp_observed_address),
                              ("root_priority", "count", _stp_observed_priority)):
        missing = ("not collected: the stored STP record carries no is_root flag" if field == "is_root" else
                   f"not collected: the spanning-tree {field.replace('_', ' ')} was not parsed")
        fact = _cell(ctx, row, field, slot, "build.build_stp_roots:stp_roots{}{}." + field, pre=pre, missing=missing,
                     caveats=("row_selection_by_exact_key",))
        # Unique integer VLAN keys are admitted by the existing owner rule. Their pointers address the JSON
        # serialization; _get intentionally only traverses string-keyed dicts. The caller has already refused
        # every serialized-pointer collision, and this literal field's presence is known from this exact record.
        if type(key) is int and isinstance(raw, dict) and field in raw:
            fact["refs"].insert(0, {"pointer": json_pointer(*toks, field), "role": "subject"})
        if type(key) is int and ("witness", toks + ("is_mst",)) in row.extra:
            fact["refs"].append({"pointer": json_pointer(*toks, "is_mst"), "role": "witness"})
        out[field] = fact
    return out


def _stp_observation_selection(ctx: _Ctx, source: Dict[str, Any], selected: Sequence[Tuple[str, Any, Any]],
                               valid_vlan: bool, vlan_toks: Tuple[Any, ...], collision: bool,
                               unreadable_maps: Sequence[Tuple[str, Sequence[Any]]],
                               uncertain_namespaces: Sequence[str]) -> Dict[str, Any]:
    state, reason = source["state"], source.get("reason")
    extras = list(unreadable_maps)
    rows = [] if collision or not valid_vlan else [_stp_observation(ctx, *entry) for entry in selected]
    bad_rows = [row["pointer"] for row, entry in zip(rows, selected) if not isinstance(entry[2], dict)]
    if state != AU and not collision:
        if not valid_vlan:
            state, reason = _UV, "unverified: this VLAN row has no readable VLAN selector for STP observations"
            extras.append(("witness", vlan_toks))
        elif unreadable_maps or bad_rows or uncertain_namespaces:
            state, reason = _UV, ("unverified: stored STP host maps, selected records or namespace markers cannot be read; "
                                  "the retained observations do not establish a complete selection")
        elif state in (_PUB, _CBE) and not rows:
            state, reason = _CBE, ("collected but empty: the readable STP map has no selected non-MST record for "
                                   "this VLAN; this proves neither root absence nor complete capture")
    result = _listing(ctx, state, reason, ("stp_roots",), "build.build_stp_roots:stp_roots{}{}", rows,
                      sections=("stp_roots",), extra=extras, caveats=("row_selection_by_exact_key",))
    # These are known selected stored records, including a unique integer key before JSON serialization.
    result["refs"].extend({"pointer": pointer, "role": "witness"} for pointer in bad_rows)
    if not collision:
        # A truthy malformed marker was excluded by the unchanged owner eligibility rule. Retain its
        # uncertainty without admitting an MST-instance record as a definite VLAN observation.
        result["refs"].extend({"pointer": pointer, "role": "witness"} for pointer in uncertain_namespaces)
    return result


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


def _vlan_wave_pre(ctx: _Ctx) -> _Pre:
    """VLANs use the producer's captured universe and exclude unscheduled hosts."""
    def subjects(row: _Row) -> Any:
        valid, number = _count(row.raw.get("vlan")) if isinstance(row.raw, dict) else (False, None)
        hosts = ctx.vlan_hosts
        if not valid or not isinstance(hosts, dict):
            return None
        values = hosts.get(number, set())
        return sorted(values) if isinstance(values, set) and all(_is_text(host) for host in values) else None

    joined = _mg_pre(ctx, subjects=subjects, include_unscheduled=False)
    blank = _blank(_R_NO_GROUP)

    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        return joined(raw, row) or blank(raw, row)

    return pre


# ---------------------------------------------------------------------------------------------------
# inventory: VLAN gateway rows (G16) -- the stored l3_forwarding rows naming a VLAN, selected, never recomputed
# ---------------------------------------------------------------------------------------------------
#: excel.write_l3_forwarding_sheet's L3 Risk flags, in the order it appends them (tracked-object-down first, then
#: single-gateway or no-FHRP, never both); the key set of analyze.ScoringConfig.l3_weights. Pinned by tests.
L3_RISK_FLAGS: Tuple[str, ...] = ("tracked-object-down", "single-gateway", "no-FHRP")
#: The flag the producer raises first, exactly when its device's captured 'show track' lists a Down object.
L3_TRACKED_DOWN_FLAG = "tracked-object-down"
#: The flag the producer raises when its VLAN has at most one gateway in the scan (gw_count <= 1).
L3_SOLE_GATEWAY_FLAG = "single-gateway"
#: The flag the producer raises for two or more gateways with no FHRP; it is never raised beside single-gateway.
L3_NO_FHRP_FLAG = "no-FHRP"
#: The producer's joiner for several flags, its word for "no flag fired and object tracking was observed", and its
#: whole-text marker for "no flag fired, but object tracking was NOT assessed" (no 'show track' capture; the
#: not-observed split of 2026-07-28). The marker is the risk text only when no flag fired.
L3_RISK_JOINER = "; "
L3_RISK_CLEAR = "ok"
L3_RISK_TRACKING_NOT_ASSESSED = NOT_OBSERVED_SENTINEL + " - no 'show track' evidence; object tracking NOT assessed"
#: analyze.compute_vlan_cutover_matrix's fhrp text for a VLAN whose gateway evidence shows exactly one gateway in the
#: scan and no FHRP (f"sole gateway on {host} (no FHRP)"): its opening and its closing. Pinned to the producer by tests.
VLAN_SOLE_GATEWAY_FHRP: Tuple[str, str] = ("sole gateway on ", " (no FHRP)")
#: excel._track_summary's text for a captured 'show track' that lists objects: '<N> obj', then ' (<D> DOWN)' when any
#: object is Down, then ' - ' and at most 6 object states. Group 2 is the Down count. Pinned to the producer by tests.
_TRACK_SUMMARY = re.compile(r"([0-9]+) obj(?: \(([0-9]+) DOWN\))?(?: - .*)?", re.DOTALL)
#: The FHRP state words (parse._parse_fhrp's role, parse.parse_hsrp_detail's state; compared without case) in which a
#: router forwards for its group and names no other router by itself: HSRP/GLBP Active and VRRP Master. Every other
#: word says another router takes part (Standby, Listen, Backup) or that the group's election is unsettled (Init,
#: Speak), so it is never read as a sole gateway.
_FHRP_SOLE_STATES = frozenset({"active", "master"})
#: The most witnesses one gap cites; its reason then states how many of how many it cites (the payload stays bounded
#: by the number of gap kinds, not by fleet size, while every count stays in-band).
_GW_GAP_WITNESS_CAP = 8
_B_GW = "excel.write_l3_forwarding_sheet:l3_forwarding[]."
_GW_CAVEAT = "vlan_gateway_rows"
_R_GW_NO_HOST = "not collected: the engine row names no switch"
_R_GW_NO_SVI_IP = ("not collected: no SVI address was recorded for this gateway. excel.write_l3_forwarding_sheet "
                   "writes '' when the row comes from an FHRP group or a connected route alone, and build.py takes "
                   "svi_ip only from the scoped interface running-config capture")
_R_GW_NO_ROLE = ("not collected: no FHRP role was recorded for this gateway. excel.write_l3_forwarding_sheet writes '' "
                 "when the device's FHRP brief names no group for this SVI or was not captured, and it does not tell "
                 "these apart, so this is not 'no FHRP'")
_R_GW_TRACK_NOT_OBSERVED = ("not collected: 'show track' was not captured on this device (the producer's own "
                            "not-observed marker), so object tracking was not assessed; this is never 'no tracking'")
_R_GW_TRACK_NONE = ("collected but empty: 'show track' was captured on this device and lists no tracked object "
                    "(not a blind spot)")
_R_GW_TRACK_LEGACY = ("not collected: an empty tracking text is ambiguous in this snapshot. Before 2026-07-28 "
                      "excel.write_l3_forwarding_sheet wrote '' both when 'show track' listed no tracked object and "
                      "when it was never captured, and this snapshot carries nothing that proves its producer "
                      "separates the two (no not-observed tracking or risk marker, and no interface marked "
                      "run_config_observed), so this is not 'no tracking'")
_R_GW_TRACK_CONTRADICTED = ("unverified: the row's risk text is the producer's 'object tracking NOT assessed' marker, "
                            "which contradicts this tracking text, so neither reading can be chosen")
_R_GW_TRACK_FLAG_CONTRADICTED = ("unverified: this tracking text and the row's tracked-object-down flag disagree. The "
                                 "producer raises that flag exactly when the device's captured 'show track' summary "
                                 "reports a Down object ('<N> obj (<D> DOWN)'), so neither reading can be chosen")
_R_GW_RISK_UNREAD = ("unverified: the stored risk text is not the producer's flag list (tracked-object-down, then "
                     "single-gateway or no-FHRP, joined by '; ' in that order; 'ok'; or its tracking-not-assessed "
                     "marker), so whether this gateway is its VLAN's sole gateway cannot be read")
_R_GW_RISK_HOSTS_UNREAD = ("unverified: {k} gateway row(s) of this VLAN name no readable switch, so the producer's "
                           "gateway count cannot be checked against the stored rows")
_R_GW_RISK_SOLE_CONTRADICTED = ("unverified: the producer flags this gateway single-gateway (its VLAN's only gateway "
                                "in the scan), yet {n} scanned devices carry a gateway row for this VLAN, so the flag "
                                "contradicts the stored rows")
_R_GW_RISK_PEER_CONTRADICTED = ("unverified: the producer raises no single-gateway flag here, which says this VLAN has "
                                "another gateway in the scan, yet only one scanned device carries a gateway row for "
                                "it, so the flags contradict the stored rows")
_R_GW_RISK_SEGMENT = ("unverified: the producer raises no single-gateway flag here because it counts a VLAN's "
                      "gateways by VLAN id across the scan, but no gateway row of this VLAN on another switch provably "
                      "shares this gateway's segment (the same readable primary subnet and SVI network, the same VRF "
                      "where both SVIs' VRFs can be read, and positive evidence of one layer-2 domain between the two "
                      "switches: a stored cable path every hop of which joins two ports trunking the VLAN, or the same "
                      "spanning-tree root bridge for the VLAN). VLAN-id reuse at another site -- even one that reuses "
                      "the subnet in the same table -- or in another VRF is not a second gateway, so whether this is "
                      "its segment's only gateway cannot be read")
_R_GW_RISK_UNPROVEN = ("{word}: the producer flags this gateway single-gateway, but the scan does not cover every "
                       "possible gateway of this VLAN: {clauses}. One gateway in the scan is not proven to be the "
                       "VLAN's only gateway")
_R_GW_FHRP_RISK_WITHHELD = ("{word}: the engine names a sole gateway for this VLAN, but that gateway row's "
                            "sole-gateway risk is withheld (its own reason and witnesses say why), so one gateway in "
                            "the scan is not proven to be the VLAN's only gateway")
_R_GW_FHRP_RISK_FALSE = ("unverified: the engine names a sole gateway for this VLAN, but that gateway row's "
                         "sole-gateway risk is published false, so the two contradict")
_R_GW_FHRP_NO_ROW = ("unverified: the engine names a sole gateway for this VLAN, but no gateway row of the VLAN names "
                     "that switch, so the two contradict")
_R_GW_FHRP_SOURCE = "{word}: the engine names a sole gateway for this VLAN, but its gateway rows cannot be read ({why})"
_R_GW_UNJOINABLE = ("{k} row(s) in l3_forwarding cannot be joined by VLAN (not an object, or a vlan that is not a VLAN "
                    "id), and any of them could be another gateway of this VLAN")
_R_GW_NO_VLAN = "unverified: this VLAN row names no readable VLAN id, so no gateway row can be joined to it"
_R_GW_NONE = ("collected but empty: no scanned device records a gateway for this VLAN "
              "(excel.write_l3_forwarding_sheet writes a row for every SVI named VlanN with an address, an FHRP group "
              "or a connected route), no other collected interface could be its gateway, and the scan covers every "
              "device the collection discovered (not a blind spot)")
_R_GW_NONE_UNPROVEN = ("{word}: no scanned device records a gateway for this VLAN, but the scan does not cover every "
                       "possible gateway of the VLAN: {clauses}; an absent gateway row is not a clean result")
_R_GW_CC_BLIND = ("collection_completeness lists {n} device(s) as partial or not collected, and any of them could "
                  "carry another gateway")
_R_GW_MAP_UNREAD = ("the stored cable map's {what} cannot be read ({why}), so no neighbour the collection never "
                    "reached can be ruled out")
_R_GW_PEERS = ("the stored cable map shows {n} neighbour(s) the collection never reached that could route (a "
               "cable_map.nodes row not marked collected: true whose kind is not ap, phone or endpoint)")
_R_GW_PEERS_LOOSE = ("{k} stored cable row(s) fail closed as such neighbours, because they cannot be read or an end "
                     "does not join exactly one cable_map.nodes row")
_R_GW_ROSTER_UNREAD = ("the {what} cannot be read ({why}), so whether every collected device's gateway SVIs were "
                       "captured cannot be checked")
_R_GW_NO_RUN_CONFIG = ("{n} collected device(s) carry no interface marked run_config_observed: true. build.py takes "
                       "SVI addresses (svi_ip) only from the scoped interface running-config capture, so an SVI of "
                       "theirs with no FHRP group and no connected route would be missing from the gateway rows")
_R_GW_ROSTER_KEYS = "{k} device key(s) in the devices or interfaces map are not text, so they name no device"
_R_GW_ADDR_UNCOUNTED_SVI = ("{n} collected SVI(s) named for this VLAN hold an address but carry no gateway row "
                            "(excel.write_l3_forwarding_sheet reads only svi_ip, an FHRP group or a connected route), "
                            "so the stored rows undercount this VLAN's gateways")
_R_GW_ADDR_IN_SEGMENT = ("{n} other collected interface(s) hold an address in this VLAN's gateway subnet, in no VRF "
                         "known to differ. excel.write_l3_forwarding_sheet counts only SVIs named VlanN for this VLAN, "
                         "so a routed port, subinterface, BDI, BVI or irb unit, or another VLAN's SVI there is never "
                         "counted, and any of them could be another gateway of this segment")
_R_GW_ADDR_UNSCOPED = ("{n} collected interface(s) not named VlanN hold an address on a subnet that leaves a host "
                       "address no collected interface holds. excel.write_l3_forwarding_sheet never counts them, the "
                       "snapshot does not store which VLAN they serve, and this VLAN's subnet cannot be read from its "
                       "gateway rows, so any of them could be its gateway")
_R_GW_ADDR_UNREAD = ("{k} collected interface record(s) or address(es) cannot be read, so whether they could gateway "
                     "this VLAN cannot be checked")
_R_GW_FHRP_ROLE = ("the gateway's own FHRP role is neither Active nor Master, so another router takes part in its "
                   "group or the group's election is unsettled")
_R_GW_FHRP_ROLE_UNREAD = ("the gateway's FHRP role cannot be read, so whether another router takes part in its group "
                          "cannot be checked")
_R_GW_FHRP_STANDBY = ("the device's HSRP detail for this SVI names a standby router that no gateway row of this VLAN "
                      "holds, a router outside the gateway rows")
_R_GW_FHRP_STATE = ("the device's HSRP detail for this SVI records a state other than Active or Master, so another "
                    "router takes part in the group or its election is unsettled")
_R_GW_FHRP_ENTRY_UNREAD = ("{k} stored HSRP detail record(s) of this device cannot be read, and any of them could name "
                           "a standby router for this SVI")
_R_GW_FHRP_NO_DETAIL = ("the gateway runs FHRP as Active or Master, but {why}, so a standby router outside the scan "
                        "cannot be ruled out")
_R_GW_FHRP_DETAIL_UNREAD = ("the stored HSRP detail (fhrp_detail) cannot be read ({why}), so a standby router it names "
                            "cannot be ruled out")
#: A gap in the scan's coverage of a VLAN's possible gateways: ``(state, reason clause, witness ref entries)``.
_GatewayGap = Tuple[str, str, List[Tuple[str, Sequence[Any]]]]


def _l3_risk_flags(raw: Any) -> Optional[Tuple[str, ...]]:
    """The producer's flags in one stored risk text (excel.write_l3_forwarding_sheet), or ``None`` when it is not its
    flag list: its clean word and its tracking-not-assessed marker both mean no flag fired; anything else must be
    distinct flags of :data:`L3_RISK_FLAGS` joined by :data:`L3_RISK_JOINER` in the producer's order (so
    tracked-object-down first), never single-gateway beside no-FHRP."""
    if not _is_text(raw):
        return None
    if raw in (L3_RISK_CLEAR, L3_RISK_TRACKING_NOT_ASSESSED):
        return ()
    flags = tuple(raw.split(L3_RISK_JOINER))
    if flags != tuple(flag for flag in L3_RISK_FLAGS if flag in flags) or (
            L3_SOLE_GATEWAY_FLAG in flags and L3_NO_FHRP_FLAG in flags):
        return None
    return flags


def _gw_gap(state: str, clause: str, wit: List[Tuple[str, Sequence[Any]]]) -> _GatewayGap:
    """One gap citing at most :data:`_GW_GAP_WITNESS_CAP` witnesses; the clause then says how many of how many."""
    if len(wit) > _GW_GAP_WITNESS_CAP:
        return state, f"{clause} ({_GW_GAP_WITNESS_CAP} of {len(wit)} cited)", wit[:_GW_GAP_WITNESS_CAP]
    return state, clause, wit


def _gap_unread(ctx: _Ctx, state: str, toks: Tuple[str, ...], section: str, clause: str) -> _GatewayGap:
    """A coverage input that cannot be read: its own failed or malformed state, else not collected, citing it."""
    st = state if state in (AU, _UV) else _NC
    where = toks if _get(ctx.s, toks) is not _MISSING else (section,)
    return st, clause, [("witness", where)] + ctx.failure_entries((section,), st == AU)


def _gateway_coverage(ctx: _Ctx) -> List[_GatewayGap]:
    """Why the scan may not cover every possible gateway of a VLAN (empty: it covers every device the collection
    discovered). Fleet-wide and fail-closed, because VLAN carriage per cable is not stored (G14), so no gap can be
    scoped to the VLANs it could reach: a collection blind spot, or any gap of the blind-spot record's one coverage
    verdict (:meth:`_Ctx.cc_coverage`: absent, failed, unreadable, or a summary that does not reconcile with its rows or
    the roster), a cable-map neighbour the collection never reached that could route (the
    failure-impact owner's :data:`impact_assessability.IMPACT_EDGE_KINDS` names the only kinds that cannot), and a
    collected device whose scoped interface running-config, the only source of its SVI addresses, was not captured (no
    interface marked run_config_observed: true, read through :func:`_run_config_captured`, the owner's scan; absent is
    never read as captured). Each input that cannot be read is a gap with its own state. The gateways
    the producer's VlanN rule cannot count are per VLAN (:meth:`_GatewayScan.attribution`)."""
    gaps: List[_GatewayGap] = []
    # the blind-spot record is read only through its one coverage verdict (W51): a listed blind spot, then every gap
    # that leaves the record unable to show each device collected or listed; a failed phase's failure records ride
    # outside the witness cap, so they are always cited
    cov = ctx.cc_coverage()
    if cov.blind:
        gaps.append(_gw_gap(_NC, _R_GW_CC_BLIND.format(n=len(cov.blind)),
                            [("witness", ("collection_completeness", "devices", i)) for i in cov.blind]))
    for cc_gap in cov.gaps:
        state, clause, wit = _gw_gap(cc_gap.state, cc_gap.clause, list(cc_gap.witness))
        gaps.append((state, clause, wit + list(cc_gap.failure)))
    ntoks, ctoks = ("cable_map", "nodes"), ("cable_map", "cables")
    nstate, nreason, nodes = _topology_source(ctx, ntoks)
    cstate, creason, cables = _topology_source(ctx, ctoks)
    for got, why, where in ((nstate, nreason, ntoks), (cstate, creason, ctoks)):
        if got not in (_PUB, _CBE):
            gaps.append(_gap_unread(ctx, got, where, "cable_map",
                                    _R_GW_MAP_UNREAD.format(what=where[1], why=why or _R_NC)))
    if nstate in (_PUB, _CBE) and isinstance(nodes, list):
        peers = []
        for i, node in enumerate(nodes):
            if isinstance(node, dict) and _is_text(node.get("host")):
                kind = node.get("kind")
                if node.get("collected") is True or (node.get("collected") is False and _is_text(kind)
                                                     and kind in impact_assessability.IMPACT_EDGE_KINDS):
                    continue
            peers.append(i)
        loose = []
        if cstate in (_PUB, _CBE) and isinstance(cables, list):
            joined = ctx.index(ntoks, ("host",))
            for j, cable in enumerate(cables):
                if not (isinstance(cable, dict) and _is_text(cable.get("a")) and _is_text(cable.get("b"))):
                    loose.append(j)
                elif len(joined.get(cable["a"], ())) != 1 or len(joined.get(cable["b"], ())) != 1:
                    loose.append(j)
        if peers:
            gaps.append(_gw_gap(_NC, _R_GW_PEERS.format(n=len(peers)), [("witness", ntoks + (i,)) for i in peers]))
        if loose:
            gaps.append(_gw_gap(_NC, _R_GW_PEERS_LOOSE.format(k=len(loose)),
                                [("witness", ctoks + (j,)) for j in loose]))
    dstate, dreason, devices = _list_state(ctx, ("devices",), ("devices",), want=dict)
    istate, ireason, ifaces = _list_state(ctx, ("interfaces",), ("interfaces",), want=dict)
    for got, why, section in ((dstate, dreason, "devices"), (istate, ireason, "interfaces")):
        if got not in (_PUB, _CBE):
            gaps.append(_gap_unread(ctx, got, (section,), section,
                                    _R_GW_ROSTER_UNREAD.format(what=section + " map", why=why or _R_NC)))
    if dstate in (_PUB, _CBE) and istate in (_PUB, _CBE) and isinstance(devices, dict) and isinstance(ifaces, dict):
        keys_seen = list(devices) + [k for k in ifaces if k not in devices]
        odd = [k for k in keys_seen if not (_is_text(k) and k)]
        uncaptured = []
        for host in sorted(k for k in keys_seen if _is_text(k) and k):
            if not _run_config_captured(ctx, host):           # the failure-impact owner's scan (one rule)
                uncaptured.append(("witness", ("interfaces", host) if host in ifaces else ("devices", host)))
        if uncaptured:
            gaps.append(_gw_gap(_NC, _R_GW_NO_RUN_CONFIG.format(n=len(uncaptured)), uncaptured))
        if odd:
            gaps.append((_UV, _R_GW_ROSTER_KEYS.format(k=len(odd)), [("witness", ("devices",)),
                                                                      ("witness", ("interfaces",))]))
    return gaps


def _tracking_split(ctx: _Ctx) -> bool:
    """Whether this snapshot proves its producer writes an empty tracking text only for a captured 'show track' that
    lists no tracked object: excel.write_l3_forwarding_sheet separates that from "never captured" since 2026-07-28
    (its not-observed tracking text and risk marker), and build.py marks run_config_observed since 2026-08-10, so
    either one in the snapshot proves the later producer. Before the split, '' meant both."""
    rows = ctx.s.get("l3_forwarding")
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, dict) and (row.get("tracking") == NOT_OBSERVED_SENTINEL
                                      or row.get("risk") == L3_RISK_TRACKING_NOT_ASSESSED):
            return True
    ifaces = ctx.s.get("interfaces")
    for ports in ifaces.values() if isinstance(ifaces, dict) else ():
        for port in ports.values() if isinstance(ports, dict) else ():
            if isinstance(port, dict) and port.get("run_config_observed") is True:
                return True
    return False


def _svi_address(raw: Any) -> Any:
    """One stored interface address ('addr mask', 'addr/len' or a bare address) as an ``ipaddress`` interface, by
    analyze.svi_subnet_leaves_no_host_address's spelling rule; ``None`` when it does not parse."""
    if not _is_text(raw):
        return None
    text = raw.strip()
    parts = text.split()
    spelled = f"{parts[0]}/{parts[1]}" if len(parts) == 2 else text
    try:
        return ipaddress.ip_interface(spelled)
    except ValueError:
        return None


def _row_segment(rec: Any) -> FrozenSet[Any]:
    """The segment networks one stored l3_forwarding row names: the network of its SVI address and its primary subnet
    (the SVI's connected route), each only when it parses as a network wider than one address."""
    if not isinstance(rec, dict):
        return frozenset()
    nets = []
    iface = _svi_address(rec.get("svi_ip"))
    if iface is not None:
        nets.append(iface.network)
    sub = rec.get("primary_subnet")
    if _is_text(sub) and sub.strip():
        try:
            nets.append(ipaddress.ip_network(sub.strip(), strict=False))
        except ValueError:
            pass
    return frozenset(net for net in nets if net.prefixlen < net.max_prefixlen)


def _port_vrf(rec: Any) -> Optional[str]:
    """The VRF one interface record names ('' for the global table), or ``None`` when it cannot be read. build.py takes
    vrf from the scoped interface running-config ('vrf forwarding', 'ip vrf forwarding', 'vrf member') or 'show vrf
    interface', so a blank vrf is the global table only where that interface's running-config was captured."""
    if not isinstance(rec, dict):
        return None
    vrf = rec.get("vrf")
    if _is_text(vrf) and vrf.strip():
        return vrf.strip()
    if (vrf is None or _is_text(vrf)) and rec.get("run_config_observed") is True:
        return ""
    return None


def _vlan_listed(raw: Any, vid: int) -> Optional[bool]:
    """Whether a stored allowed-VLAN text ('10,20,30', ranges '1-4094', 'ALL', 'none') lists VLAN `vid`; ``None`` when
    any part of it cannot be read (the owners' VLAN-id key rule, :func:`_vid`; a range outside 1-4094 is unreadable)."""
    if not _is_text(raw):
        return None
    text = raw.strip().lower()
    if text == "all":
        return 1 <= vid <= 4094
    if text in ("", "none"):
        return False
    hit = False
    for part in text.split(","):
        lo_text, sep, hi_text = part.strip().partition("-")
        lo = _vid(lo_text)
        hi = _vid(hi_text) if sep else lo
        if lo is None or hi is None or not 1 <= lo <= hi <= 4094:
            return None
        hit = hit or lo <= vid <= hi
    return hit


def _trunks_vlan(rec: Any, vid: int) -> bool:
    """One stored interface record is a port trunking VLAN `vid`: its trunk status is 'trunking' and its allowed-VLAN
    list (build.py's trunk_allowed_vlans) can be read and lists the VLAN. Anything else carries no proof."""
    if not isinstance(rec, dict):
        return False
    status = rec.get("trunk_status")
    return (_is_text(status) and status.strip().lower() == "trunking"
            and _vlan_listed(rec.get("trunk_allowed_vlans"), vid) is True)


def _stp_root(snap: Mapping[str, Any], host: str, vid: int) -> Optional[str]:
    """The spanning-tree root bridge `host` reports for VLAN `vid` (build.build_stp_roots: stp_roots{host}{vid}), as
    lower-case text, only for a per-VLAN instance (is_mst exactly false) whose root address can be read; else
    ``None``. A bridge address names one bridge, so two switches reporting it share that VLAN's spanning tree."""
    roots = snap.get("stp_roots")
    per_host = roots.get(host) if isinstance(roots, dict) else None
    rec = per_host.get(str(vid)) if isinstance(per_host, dict) else None
    if not (isinstance(rec, dict) and rec.get("is_mst") is False):
        return None
    address = rec.get("root_address")
    return address.strip().lower() if _is_text(address) and address.strip() else None


def _interface_addresses(rec: Mapping[str, Any], base: Tuple[Any, ...]) -> Tuple[List[Any], List[Tuple[Any, ...]]]:
    """Every address one interface record holds (svi_ip, and the configured set svi_ips, ';'-joined text or a list),
    parsed, and the tokens of every address value that cannot be read."""
    found: List[Any] = []
    bad: List[Tuple[Any, ...]] = []
    values: List[Tuple[Any, Tuple[Any, ...]]] = [(rec["svi_ip"], base + ("svi_ip",))] if "svi_ip" in rec else []
    many = rec.get("svi_ips")
    if _is_text(many):
        values += [(value, base + ("svi_ips",)) for value in many.split(";")]
    elif isinstance(many, list):
        values += [(value, base + ("svi_ips", k)) for k, value in enumerate(many)]
    elif many is not None:
        bad.append(base + ("svi_ips",))
    for raw, toks in values:
        if raw is None or (_is_text(raw) and not raw.strip()):
            continue
        iface = _svi_address(raw)
        if iface is None:
            bad.append(toks)
        elif iface not in found:
            found.append(iface)
    return found, bad


class _GatewayScan:
    """What every VLAN's gateway rows read, once per projection (G16): the fleet-wide coverage gaps, the tracking-split
    proof, the l3_forwarding join, and every collected interface address. excel.write_l3_forwarding_sheet counts only
    interfaces named VlanN, so the addresses are what can show a gateway it never counted."""

    def __init__(self, ctx: _Ctx) -> None:
        self.ctx = ctx
        rows = ctx.s.get("l3_forwarding")
        self.by_vid = _vid_index(ctx, ("l3_forwarding",))
        self.loose = [j for j, rec in enumerate(rows if isinstance(rows, list) else ())
                      if not (isinstance(rec, dict) and _vid(rec.get("vlan")) is not None)]
        self.cover = _gateway_coverage(ctx)
        self.split = _tracking_split(ctx)
        #: (host, port, address, the port's VLAN id or None) of every readable collected interface address
        self.held: List[Tuple[str, str, Any, Optional[int]]] = []
        #: (host, port, witness tokens, the port's VLAN id or None) of every record or address that cannot be read
        self.bad: List[Tuple[str, str, Tuple[Any, ...], Optional[int]]] = []
        #: (host, VLAN id) -> its ports named for that VLAN (compute_vlan_cutover_matrix's SVI rule)
        self.svis: Dict[Tuple[str, int], List[str]] = {}
        #: VLAN id -> (host, port) of every SVI named for it that holds an address
        self.addressed: Dict[int, List[Tuple[str, str]]] = {}
        self._by_len: Dict[Tuple[int, int], Dict[int, List[int]]] = {}
        self._free: Dict[Any, bool] = {}
        self._unscoped: Optional[List[Tuple[str, str]]] = None
        #: VLAN id -> the trunk graph :meth:`same_l2` walks (built on first use)
        self._l2: Dict[int, Dict[str, Set[str]]] = {}
        ifaces = ctx.s.get("interfaces")
        for host in [k for k in ifaces if _is_text(k) and k] if isinstance(ifaces, dict) else ():
            ports = ifaces[host]
            for port in [p for p in ports if _is_text(p)] if isinstance(ports, dict) else ():
                match = _SVI.match(port)
                vid = _vid(match.group(1)) if match else None
                if vid is not None:
                    self.svis.setdefault((host, vid), []).append(port)
                base = ("interfaces", host, port)
                rec = ports[port]
                if not isinstance(rec, dict):
                    self.bad.append((host, port, base, vid))
                    continue
                found, bad = _interface_addresses(rec, base)
                self.bad += [(host, port, toks, vid) for toks in bad]
                self.held += [(host, port, iface, vid) for iface in found]
                if found and vid is not None:
                    self.addressed.setdefault(vid, []).append((host, port))

    def within(self, net: Any) -> List[int]:
        """Indices into :attr:`held` of every address inside `net` (one index per prefix length, built on first use)."""
        key = (net.version, net.prefixlen)
        shift = net.max_prefixlen - net.prefixlen
        if key not in self._by_len:
            index: Dict[int, List[int]] = {}
            for i, (_host, _port, iface, _vid_of) in enumerate(self.held):
                if iface.version == net.version:
                    index.setdefault(int(iface.ip) >> shift, []).append(i)
            self._by_len[key] = index
        return list(self._by_len[key].get(int(net.network_address) >> shift, ()))

    def leaves_host(self, net: Any) -> bool:
        """Whether `net` leaves a usable host address that no collected interface holds, over
        analyze.svi_subnet_leaves_no_host_address's usable set (both addresses of a two-address network, every host of
        one up to 256 addresses); a larger network always does."""
        if net not in self._free:
            if net.num_addresses > 256:
                self._free[net] = True
            else:
                usable = ({net.network_address, net.broadcast_address} if net.num_addresses == 2
                          else set(net.hosts()))
                self._free[net] = bool(usable - {self.held[i][2].ip for i in self.within(net)})
        return self._free[net]

    def unscoped(self) -> List[Tuple[str, str]]:
        """Every collected interface not named VlanN that holds an address on a subnet leaving a host address free: a
        gateway the producer never counts, for a VLAN the snapshot does not store."""
        if self._unscoped is None:
            seen: Dict[Tuple[str, str], None] = {}
            for host, port, iface, vid in self.held:
                if vid is None and (host, port) not in seen and self.leaves_host(iface.network):
                    seen[(host, port)] = None
            self._unscoped = list(seen)
        return list(self._unscoped)

    def same_l2(self, a: str, b: str, vid: int) -> bool:
        """Positive stored evidence that switches `a` and `b` share one layer-2 domain for VLAN `vid` (W51): both
        report the same spanning-tree root bridge for it (:func:`_stp_root`), or a stored cable path joins them every
        hop of which is a cable_map.cables row whose two ends are collected ports trunking the VLAN
        (:func:`_trunks_vlan`). A matching subnet, VRF, FHRP group or virtual address is not such evidence: cloned
        sites reuse every one of them. Anything that cannot be read proves nothing."""
        root = _stp_root(self.ctx.s, a, vid)
        if root is not None and root == _stp_root(self.ctx.s, b, vid):
            return True
        if vid not in self._l2:
            self._l2[vid] = self._trunk_graph(vid)
        graph = self._l2[vid]
        seen, frontier = {a}, [a]
        while frontier:
            here = frontier.pop()
            for there in graph.get(here, ()):
                if there == b:
                    return True
                if there not in seen:
                    seen.add(there)
                    frontier.append(there)
        return False

    def _trunk_graph(self, vid: int) -> Dict[str, Set[str]]:
        """Host -> the hosts one stored cable joins it to over two ports both trunking VLAN `vid`."""
        graph: Dict[str, Set[str]] = {}
        cables = _get(self.ctx.s, ("cable_map", "cables"))
        ifaces = self.ctx.s.get("interfaces")
        if not (isinstance(cables, list) and isinstance(ifaces, dict)):
            return graph
        for cable in cables:
            if not isinstance(cable, dict):
                continue
            ends = [(cable.get(h), cable.get(p)) for h, p in (("a", "a_port"), ("b", "b_port"))]
            if not all(_is_text(host) and host and _is_text(port) and port for host, port in ends):
                continue
            (ha, pa), (hb, pb) = ends
            if ha == hb:
                continue
            ports_a, ports_b = ifaces.get(ha), ifaces.get(hb)
            if not (isinstance(ports_a, dict) and isinstance(ports_b, dict)):
                continue
            if _trunks_vlan(ports_a.get(pa), vid) and _trunks_vlan(ports_b.get(pb), vid):
                graph.setdefault(ha, set()).add(hb)
                graph.setdefault(hb, set()).add(ha)
        return graph

    def vrf(self, host: Any, vid: int) -> Optional[str]:
        """The VRF of `host`'s one SVI for VLAN `vid` (:func:`_port_vrf`), or ``None`` when no single such port exists
        or its VRF cannot be read."""
        ports = self.svis.get((host, vid), []) if _is_text(host) else []
        if len(ports) != 1:
            return None
        return _port_vrf(self.ctx.s["interfaces"][host][ports[0]])

    def attribution(self, vid: int, hosts: FrozenSet[str], segments: Sequence[FrozenSet[Any]],
                    vrfs: Sequence[Optional[str]]) -> List[_GatewayGap]:
        """The gateways of VLAN `vid` the producer's VlanN rule could not count, from the collected interface
        addresses: an addressed SVI named for the VLAN on a switch with no gateway row; any other interface holding an
        address in a segment the VLAN's rows name (outside a VRF known to differ); where a row names no readable
        segment (or the VLAN has no row), any interface not named VlanN on a subnet leaving a host address free; and
        every record or address that cannot be read, except on the VLAN's own counted SVIs."""
        gaps: List[_GatewayGap] = []
        uncounted = [hp for hp in self.addressed.get(vid, ()) if hp[0] not in hosts]
        if uncounted:
            gaps.append(_gw_gap(_UV, _R_GW_ADDR_UNCOUNTED_SVI.format(n=len(uncounted)),
                                [("witness", ("interfaces",) + hp) for hp in uncounted]))
        known = set(vrfs) if vrfs and all(v is not None for v in vrfs) else None
        ifaces = self.ctx.s.get("interfaces")
        hits: Dict[Tuple[str, str], None] = {}
        for net in sorted({net for seg in segments for net in seg}, key=str):
            for i in self.within(net):
                host, port, _iface, pvid = self.held[i]
                if pvid == vid or (host, port) in hits:
                    continue
                pvrf = _port_vrf(ifaces[host][port])
                if known is not None and pvrf is not None and pvrf not in known:
                    continue
                hits[(host, port)] = None
        if hits:
            gaps.append(_gw_gap(_UV, _R_GW_ADDR_IN_SEGMENT.format(n=len(hits)),
                                [("witness", ("interfaces",) + hp) for hp in hits]))
        if not segments or not all(segments):
            rest = [hp for hp in self.unscoped() if hp not in hits]
            if rest:
                gaps.append(_gw_gap(_NC, _R_GW_ADDR_UNSCOPED.format(n=len(rest)),
                                    [("witness", ("interfaces",) + hp) for hp in rest]))
        bad = [toks for host, _port, toks, pvid in self.bad if not (pvid == vid and host in hosts)]
        if bad:
            gaps.append(_gw_gap(_UV, _R_GW_ADDR_UNREAD.format(k=len(bad)), [("witness", toks) for toks in bad]))
        return gaps

    def fhrp_gaps(self, j: int, rec: Mapping[str, Any], vid: int, owned: FrozenSet[Any]) -> List[_GatewayGap]:
        """Stored FHRP evidence that another router takes part in this gateway's group, which a sole-gateway reading
        would contradict: the row's own role (any word but Active or Master), and the device's HSRP detail
        (parse.parse_hsrp_detail via build.build_fhrp_detail) for its SVI naming a standby router no gateway row of
        the VLAN holds, or a state other than Active or Master. An Active or Master gateway whose detail is absent
        cannot rule out a standby router outside the scan; a detail record or section that cannot be read could name
        one."""
        ctx = self.ctx
        gaps: List[_GatewayGap] = []
        host, role = rec.get("switch"), rec.get("role")
        active = False
        if role is not None and not _is_text(role):           # absent or '': no role recorded (the role cell says so)
            gaps.append((_UV, _R_GW_FHRP_ROLE_UNREAD, [("witness", ("l3_forwarding", j, "role"))]))
        elif _is_text(role) and role.strip():
            if role.strip().lower() in _FHRP_SOLE_STATES:
                active = True
            else:
                gaps.append((_UV, _R_GW_FHRP_ROLE, [("witness", ("l3_forwarding", j, "role"))]))
        toks = ("fhrp_detail",)
        state, reason, detail = _list_state(ctx, toks, toks, want=dict)
        if state not in (_PUB, _CBE):
            if active or state in (AU, _UV):
                gaps.append(_gap_unread(ctx, state, toks, "fhrp_detail",
                                        _R_GW_FHRP_DETAIL_UNREAD.format(why=reason or _R_NC)))
            return gaps
        records = detail.get(host, _MISSING) if _is_text(host) and isinstance(detail, dict) else _MISSING
        if records is _MISSING:
            if active:
                gaps.append((_NC, _R_GW_FHRP_NO_DETAIL.format(why="no HSRP detail is stored for this device"),
                             [("witness", toks)]))
            return gaps
        if not isinstance(records, list):
            return gaps + [(_UV, _R_GW_FHRP_ENTRY_UNREAD.format(k=1), [("witness", toks + (host,))])]
        mine = 0
        unread: List[Tuple[str, Sequence[Any]]] = []
        for i, entry in enumerate(records):
            here = toks + (host, i)
            name = entry.get("ifname") if isinstance(entry, dict) else None
            match = _SVI.match(name) if _is_text(name) else None
            if not _is_text(name):
                unread.append(("witness", here))
                continue
            if not (match and _vid(match.group(1)) == vid):
                continue
            mine += 1
            standby, group_state = entry.get("standby_ip"), entry.get("state")
            if not ((standby is None or _is_text(standby)) and (group_state is None or _is_text(group_state))):
                unread.append(("witness", here))
                continue
            if _is_text(standby) and standby.strip():
                addr = _svi_address(standby)
                if addr is None or addr.ip not in owned:
                    gaps.append((_UV, _R_GW_FHRP_STANDBY, [("witness", here + ("standby_ip",))]))
            if _is_text(group_state) and group_state.strip() and group_state.strip().lower() not in _FHRP_SOLE_STATES:
                gaps.append((_UV, _R_GW_FHRP_STATE, [("witness", here + ("state",))]))
        if unread:
            gaps.append(_gw_gap(_UV, _R_GW_FHRP_ENTRY_UNREAD.format(k=len(unread)), unread))
        if active and not mine:
            gaps.append((_NC, _R_GW_FHRP_NO_DETAIL.format(why="no stored HSRP detail record of this device names "
                                                              "its SVI"), [("witness", toks + (host,))]))
        return gaps


def _gateway_tracking_pre(split: bool) -> _Pre:
    """The tracking cell: a text that disagrees with the row's own tracked-object-down flag (the producer raises it
    exactly when its summary reports a Down object) is unverified; the producer's not-observed marker is never 'no
    tracking'; a tracking text beside the row's own tracking-not-assessed risk marker contradicts it; and an empty
    text is a captured 'show track' with no tracked object only where :func:`_tracking_split` proves the producer
    separates the two."""
    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        risk = row.raw.get("risk") if isinstance(row.raw, dict) else None
        flags = _l3_risk_flags(risk)
        wit = [("witness", row.toks + ("risk",))]
        if _is_text(raw) and flags is not None:
            shape = _TRACK_SUMMARY.fullmatch(raw)
            down = bool(shape and shape.group(2) and int(shape.group(2)) > 0)
            if down != (L3_TRACKED_DOWN_FLAG in flags):
                return _UV, _R_GW_TRACK_FLAG_CONTRADICTED, wit
        if raw == NOT_OBSERVED_SENTINEL:
            return _NC, _R_GW_TRACK_NOT_OBSERVED
        if _is_text(raw) and risk == L3_RISK_TRACKING_NOT_ASSESSED:
            return _UV, _R_GW_TRACK_CONTRADICTED, wit
        if raw == "":
            return (_CBE, _R_GW_TRACK_NONE) if split else (_NC, _R_GW_TRACK_LEGACY)
        return None
    return pre


def _gateway_segment_hold(scan: _GatewayScan, vid: int, j: int, sel: Sequence[int], recs: Mapping[int, Any],
                          segs: Mapping[int, FrozenSet[Any]]) -> Optional[Tuple[Any, ...]]:
    """``None`` when another switch's gateway row of the VLAN provably shares row `j`'s segment: the same readable
    primary subnet and SVI network, the same VRF where both SVIs' VRFs can be read, and (W51) positive evidence that
    the two switches share one layer-2 domain for the VLAN (:meth:`_GatewayScan.same_l2`). The producer counts
    gateways by VLAN id across the scan, so without that proof a second row may be VLAN-id reuse -- at another site
    that reuses the subnet in the same table too -- not a second gateway, and the false it implies is unverified,
    citing every row of the VLAN and their SVIs (bounded by the gap cap)."""
    host = recs[j]["switch"]
    mine, my_vrf = segs[j], scan.vrf(host, vid)
    for k in sel:
        other = recs[k]["switch"]
        if other != host and mine and segs[k] == mine:
            theirs = scan.vrf(other, vid)
            if (my_vrf is None or theirs is None or my_vrf == theirs) and scan.same_l2(host, other, vid):
                return None
    order = [j] + [k for k in sel if k != j]
    wit: List[Tuple[str, Sequence[Any]]] = []
    for k in order:
        wit.append(("witness", ("l3_forwarding", k)))
        wit += [("witness", ("interfaces", recs[k]["switch"], port))
                for port in scan.svis.get((recs[k]["switch"], vid), ())]
    state, reason, entries = _gw_gap(_UV, _R_GW_RISK_SEGMENT, wit)
    return state, reason, entries


def _gateway_risk_pre(scan: _GatewayScan, vid: int, sel: Sequence[int], recs: Mapping[int, Any], n_hosts: int,
                      unnamed: Sequence[int], cover: Sequence[_GatewayGap],
                      segs: Mapping[int, FrozenSet[Any]]) -> _Pre:
    """The sole-gateway risk cell. The producer's single-gateway flag must agree with the stored rows: it says the
    VLAN has exactly one scanned gateway, and its absence says it has two or more. Its absence is published as false
    only where another switch's gateway row provably shares this row's segment (:func:`_gateway_segment_hold`), and
    then whatever the coverage, because an unscanned device can only add gateways. The flag itself is published as
    true only when the scan covers every possible gateway of the VLAN (``cover``: the fleet gaps of
    :func:`_gateway_coverage` and the VLAN's :meth:`_GatewayScan.attribution`), no row l3_forwarding cannot join by
    VLAN could be that other gateway, and no stored FHRP record shows another router in its group
    (:meth:`_GatewayScan.fhrp_gaps`)."""
    owned = frozenset(addr.ip for addr in (_svi_address(recs[k].get("svi_ip")) for k in sel) if addr is not None)

    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        flags = _l3_risk_flags(raw)
        if flags is None:
            return _UV, _R_GW_RISK_UNREAD
        if unnamed:
            return (_UV, _R_GW_RISK_HOSTS_UNREAD.format(k=len(unnamed)),
                    [("witness", ("l3_forwarding", k)) for k in unnamed])
        j = row.toks[-1]
        sole = L3_SOLE_GATEWAY_FLAG in flags
        if sole and n_hosts != 1:
            return (_UV, _R_GW_RISK_SOLE_CONTRADICTED.format(n=n_hosts),
                    [("witness", ("l3_forwarding", k)) for k in sel])
        loose_gap = [_gw_gap(_UV, _R_GW_UNJOINABLE.format(k=len(scan.loose)),
                             [("witness", ("l3_forwarding", k)) for k in scan.loose])] if scan.loose else []
        if not sole:
            if n_hosts < 2:
                if loose_gap:                    # the other gateway may be a row the join cannot read
                    return _UV, "unverified: " + loose_gap[0][1], loose_gap[0][2]
                return _UV, _R_GW_RISK_PEER_CONTRADICTED, [("witness", ("l3_forwarding", k)) for k in sel]
            return _gateway_segment_hold(scan, vid, j, sel, recs, segs)
        gaps = list(cover) + loose_gap + scan.fhrp_gaps(j, recs[j], vid, owned)
        if gaps:
            state = impact_assessability.bound_state(gaps)
            return (state, _R_GW_RISK_UNPROVEN.format(word=impact_assessability.STATE_WORD[state],
                                                      clauses="; ".join(gap[1] for gap in gaps)),
                    [w for gap in gaps for w in gap[2]])
        return None
    return pre


#: One gateway row's sole-gateway risk as the VLAN row's fhrp cell reads it: ``(risk fact, the ref entries its
#: pre-check cited, the row's raw switch)``.
_GatewayRisk = Tuple[Dict[str, Any], List[Tuple[str, Sequence[Any]]], Any]


def _vlan_fhrp_pre(ctx: _Ctx, src_state: str, listing: Mapping[str, Any], risks: Mapping[int, _GatewayRisk]) -> _Pre:
    """The VLAN row's fhrp cell: the engine's not-observed marker as before, and its "sole gateway on <host> (no FHRP)"
    text only where the gateway row of that switch publishes its sole-gateway risk true, so one VLAN row never states
    a sole gateway in one cell and withholds it in another, whatever withheld the risk. A withheld risk lends its
    state and witnesses; a published false, or no gateway row naming the switch, contradicts the text. Its other
    texts (two or more gateways without FHRP, a transit subnet) and its FHRP record pass through."""
    opening, closing = VLAN_SOLE_GATEWAY_FHRP

    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        early = _marker(raw, row)
        if early is not None:
            return early
        if not (_is_text(raw) and len(raw) >= len(opening) + len(closing) and raw.startswith(opening)
                and raw.endswith(closing)):
            return None
        host = raw[len(opening):len(raw) - len(closing)]
        named = [(j, fact, held) for j, (fact, held, switch) in risks.items() if switch == host]
        if any(fact["state"] == _PUB and fact.get("value") is True for _j, fact, _held in named):
            return None
        withheld = [(j, fact, held) for j, fact, held in named if fact["state"] != _PUB]
        if withheld:
            j, fact, held = withheld[0]
            state = fact["state"] if fact["state"] in impact_assessability.STATE_WORD else _UV
            return (state, _R_GW_FHRP_RISK_WITHHELD.format(word=impact_assessability.STATE_WORD[state]),
                    [("witness", ("l3_forwarding", j, "risk")), ("witness", ("l3_forwarding", j))] + held
                    + ctx.failure_entries(("l3_forwarding",), state == AU))
        if named:
            j = named[0][0]
            return _UV, _R_GW_FHRP_RISK_FALSE, [("witness", ("l3_forwarding", j, "risk"))]
        if src_state not in (_PUB, _CBE) or listing["state"] in (AU, _UV):
            state = listing["state"] if listing["state"] in impact_assessability.STATE_WORD else _UV
            return (state, _R_GW_FHRP_SOURCE.format(word=impact_assessability.STATE_WORD[state],
                                                    why=listing.get("reason") or _R_NC),
                    [("witness", ("l3_forwarding",))] + ctx.failure_entries(("l3_forwarding",), state == AU))
        return _UV, _R_GW_FHRP_NO_ROW, [("witness", ("l3_forwarding",))]
    return pre


def _gateway_row(ctx: _Ctx, j: int, rec: Any, risk_pre: _Pre,
                 tracking_pre: _Pre) -> Tuple[Dict[str, Any], List[Tuple[str, Sequence[Any]]]]:
    """One stored l3_forwarding row as a gateway of its VLAN: its switch, SVI address, FHRP role and tracking as the
    producer wrote them, and the sole-gateway risk read from its single-gateway flag (a boolean, never the producer's
    other flags); with the ref entries the risk's pre-check cited when it withheld the risk."""
    toks = ("l3_forwarding", j)
    row = _list_row(toks, rec, ("l3_forwarding",))
    held: List[Tuple[str, Sequence[Any]]] = []

    def risk_hold(raw: Any, cell_row: _Row) -> Optional[Tuple[Any, ...]]:
        out = risk_pre(raw, cell_row)
        if out is not None and len(out) > 2:
            held.extend(out[2])
        return out

    out: Dict[str, Any] = {"index": j, "pointer": json_pointer(*toks)}
    out["host"] = _cell(ctx, row, "switch", "text", _B_GW + "switch", pre=_blank(_R_GW_NO_HOST))
    out["svi_ip"] = _cell(ctx, row, "svi_ip", "text", _B_GW + "svi_ip", pre=_blank(_R_GW_NO_SVI_IP))
    out["role"] = _cell(ctx, row, "role", "text", _B_GW + "role", pre=_blank(_R_GW_NO_ROLE),
                        published_caveats=(_GW_CAVEAT,))
    out["tracking"] = _cell(ctx, row, "tracking", "text", _B_GW + "tracking", pre=tracking_pre,
                            published_caveats=(_GW_CAVEAT,))
    risk = _cell(ctx, row, "risk", "text", _B_GW + "risk (its single-gateway flag: the sole-gateway risk)",
                 pre=risk_hold, published_caveats=(_GW_CAVEAT,))
    if risk["state"] == _PUB:
        risk["value"] = L3_SOLE_GATEWAY_FLAG in (_l3_risk_flags(risk["value"]) or ())
    out["risk"] = risk
    return out, held


def _vlan_gateways(ctx: _Ctx, src: Tuple[str, Optional[str], Any], ok: bool, vid: Any,
                   scan: _GatewayScan) -> Tuple[Dict[str, Any], Dict[int, _GatewayRisk]]:
    """``selections.gateways`` of one VLAN row: the stored l3_forwarding rows naming its VLAN id (the owners' key rule,
    :func:`_vid`), each a :func:`_gateway_row`, and each row's risk as the fhrp cell reads it. Never a clean absence
    by silence: a row the join cannot read makes the list unverified (it could name this VLAN), and an empty selection
    is collected but empty only when the scan covers every possible gateway of the VLAN. A published list under a
    coverage gap may be incomplete and cites the gap."""
    toks = ("l3_forwarding",)
    base, reason, raw = src
    basis = "excel.write_l3_forwarding_sheet:l3_forwarding[] (the rows naming this VLAN)"
    cav = ("row_selection_by_exact_key",)
    # A failed, absent or unreadable source selects nothing (selection_sources says why, as before G16); a list the
    # abstention core calls empty although it holds rows is still read, and stays unverified below.
    if not (base in (_PUB, _CBE) or (base == _UV and isinstance(raw, list))):
        return _listing(ctx, base, reason, toks, basis, [], sections=toks, caveats=cav), {}
    sel = list(scan.by_vid.get(vid, ())) if ok else []
    recs = {j: raw[j] for j in sel}                       # _vid_index selects objects only
    unnamed = [j for j in sel if not (_is_text(recs[j].get("switch")) and recs[j]["switch"])]
    hosts = frozenset(recs[j]["switch"] for j in sel if j not in unnamed)
    segs = {j: _row_segment(recs[j]) for j in sel}
    cover = list(scan.cover)
    if ok:
        cover += scan.attribution(vid, hosts, [segs[j] for j in sel],
                                  [scan.vrf(recs[j]["switch"], vid) for j in sel if j not in unnamed])
    risk_pre = _gateway_risk_pre(scan, vid, sel, recs, len(hosts), unnamed, cover, segs)
    tracking_pre = _gateway_tracking_pre(scan.split)
    items: List[Dict[str, Any]] = []
    risks: Dict[int, _GatewayRisk] = {}
    for j in sel:
        item, held = _gateway_row(ctx, j, recs[j], risk_pre, tracking_pre)
        items.append(item)
        risks[j] = (item["risk"], held, recs[j].get("switch"))
    doubts = [reason] if base == _UV and reason else []
    wit: List[Tuple[str, Sequence[Any]]] = []
    if not ok:
        doubts.append(_R_GW_NO_VLAN)
    elif scan.loose:
        _st, clause, cited = _gw_gap(_UV, _R_GW_UNJOINABLE.format(k=len(scan.loose)),
                                     [("witness", toks + (j,)) for j in scan.loose])
        doubts.append("unverified: " + clause)
        wit += cited
    if doubts or base == _UV:
        return _listing(ctx, _UV, "; ".join(doubts) or _R_OWNER_EMPTY, toks, basis, items, sections=toks, extra=wit,
                        caveats=cav), risks
    gap_state = impact_assessability.bound_state(cover) if cover else _NC
    unproven = _R_GW_NONE_UNPROVEN.format(word=impact_assessability.STATE_WORD[gap_state],
                                          clauses="; ".join(gap[1] for gap in cover))
    gap_wit = [w for gap in cover for w in gap[2]]
    if not sel:
        if cover:
            return _listing(ctx, gap_state, unproven, toks, basis, [], sections=toks, extra=gap_wit,
                            caveats=cav), risks
        return _listing(ctx, _CBE, _R_GW_NONE, toks, basis, [], sections=toks, caveats=cav), risks
    qualify = _fleet_qualify(ctx) + ([(_GW_CAVEAT, unproven, gap_wit)] if cover else [])
    return _listing(ctx, _PUB, None, toks, basis, items, sections=toks, caveats=cav, qualify=qualify), risks


def _vlan_rows(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("vlan_cutover",)
    base, reason, raw = _list_state(ctx, toks, toks)
    src_roots, ok_roots = _source(ctx, ("stp_roots",), ("stp_roots",), "build.build_stp_roots:stp_roots{}{}", want=dict)
    source_roots = ctx.s.get("stp_roots")
    root_pointers = [json_pointer("stp_roots", host, key)
                     for host, per_host in (source_roots.items() if isinstance(source_roots, dict) else ())
                     if _is_text(host) and host and isinstance(per_host, dict)
                     for key in per_host if _stp_vlan_key(key) is not None]
    root_collision = len(set(root_pointers)) != len(root_pointers)
    if ok_roots and root_collision:
        src_roots.update(state=_UV, reason="unverified: STP map keys collide when serialized as RFC 6901 pointers")
        ok_roots = False
    unreadable_root_maps = [("witness", ("stp_roots", host) if _is_text(host) else ("stp_roots",))
                            for host, records in (source_roots.items() if isinstance(source_roots, dict) else ())
                            if not _is_text(host) or not host or not isinstance(records, dict)]
    uncertain_namespaces: Dict[int, List[str]] = {}
    for host, records in (source_roots.items() if isinstance(source_roots, dict) else ()):
        if not _is_text(host) or not host or not isinstance(records, dict):
            continue
        for key, record in records.items():
            vid = _stp_vlan_key(key)
            if (vid is not None and isinstance(record, dict) and "is_mst" in record
                    and type(record["is_mst"]) is not bool):
                uncertain_namespaces.setdefault(vid, []).extend(
                    (json_pointer("stp_roots", host, key), json_pointer("stp_roots", host, key, "is_mst")))
    src_gw = _source(ctx, ("l3_forwarding",), ("l3_forwarding",), "excel.write_l3_forwarding_sheet:l3_forwarding[]")[0]
    src_ep, ok_ep = _source(ctx, ("endpoint_identity",), ("endpoint_identity",),
                            "analyze.compute_endpoint_identity:endpoint_identity[]")
    roots, endpoints = _stp_root_index(ctx), _vid_index(ctx, ("endpoint_identity",))
    # G16: every VLAN row's gateway list reads one source state and one scan (the join census, the coverage verdict
    # and the collected interface addresses), built on the first VLAN row.
    gw_src = _list_state(ctx, ("l3_forwarding",), ("l3_forwarding",))
    gw_scan: Optional[_GatewayScan] = None
    pres = {"dependencies": _vlan_deps_pre(ctx), "wave": _vlan_wave_pre(ctx)}
    capped = ENGINE_LIST_CAPS["vlan_cutover[].app_domain"]
    owner_rows: Dict[int, List[int]] = {}
    for index, record in enumerate(raw if isinstance(raw, list) else ()):
        valid, number = _count(record.get("vlan")) if isinstance(record, dict) else (False, None)
        if valid:
            owner_rows.setdefault(number, []).append(index)
    items: List[Dict[str, Any]] = []
    for i, rec in enumerate(raw if isinstance(raw, list) else ()):
        row = _list_row(toks + (i,), rec, toks)
        item: Dict[str, Any] = {"index": i, "pointer": json_pointer(*toks, i)}
        ok, vid = _count(rec.get("vlan")) if isinstance(rec, dict) else (False, None)
        duplicates = owner_rows.get(vid, []) if ok else []
        if gw_scan is None:
            gw_scan = _GatewayScan(ctx)
        # the gateway rows first: the fhrp cell states a sole gateway only where that gateway's own risk is true
        gw_list, gw_risks = _vlan_gateways(ctx, gw_src, ok, vid, gw_scan)
        row_pres = {**pres, "fhrp": _vlan_fhrp_pre(ctx, gw_src[0], gw_list, gw_risks)}

        def duplicate_owner_pre(_raw: Any, _row: _Row) -> Optional[Tuple[Any, ...]]:
            return (_UV, "unverified: multiple published VLAN rows name this VLAN; no single STP verdict is "
                    "identifiable", [("witness", toks + (j,)) for j in duplicates])

        for field, (slot, vocab, pre, empty, pub_cav) in _VLAN_CELLS.items():
            if field == "app_domain":
                dom = rec.get("app_domain") if isinstance(rec, dict) else None
                if _is_text(dom) and dom and len(dom.split(APP_DOMAIN_JOINER)) >= capped:
                    pub_cav = pub_cav + ("engine_list_capped",)
            ready = field == "readiness" and isinstance(rec, dict) and rec.get(field) == "READY"
            check = (duplicate_owner_pre if len(duplicates) > 1 and (field.startswith("stp_root") or ready)
                     else row_pres.get(field, pre))
            item[field] = _cell(ctx, row, field, slot, _B_VLAN + field, vocab=vocab,
                                sections=toks + VLAN_FIELD_BASIS[field], pre=check, empty=empty,
                                published_caveats=pub_cav)
        item["selections"] = {"stp_roots": _stp_observation_selection(
                                  ctx, src_roots, roots.get(vid, ()) if ok else (), ok, toks + (i,),
                                  root_collision, unreadable_root_maps,
                                  sorted(uncertain_namespaces.get(vid, ())) if ok else ()),
                              "gateways": gw_list,
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
                             pre=_mg_pre(ctx, "move_groups")),
        "split_across_groups": _cell(ctx, row, "split_across_groups", "flag", basis + "split_across_groups",
                                     sections=mg_secs, pre=_mg_pre(ctx, "split_across_groups")),
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
                         caveats=("engine_list_capped",) + (("move_group_label_absent",) if ctx.mg_legacy else ()),
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


def _evidence_target(snap: Dict[str, Any], pointer: str) -> Any:
    """Resolve an already syntax-checked RFC 6901 pointer, including pre-JSON integer map keys.

    Array indexes are canonical ASCII decimals; bound their length before integer conversion. A null
    target is not observed evidence. Decoding happens once, preserving a literal '~1' from '~01'.
    """
    cur: Any = snap
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            matches = [cur[token]] if token in cur else []
            for key, value in cur.items():
                if type(key) is int:
                    try:
                        if str(key) == token:
                            matches.append(value)
                    except ValueError:  # poisoned integers can exceed Python's string-conversion limit
                        continue
            if len(matches) != 1:  # JSON-serialization collisions cannot identify one observed node
                return _MISSING
            cur = matches[0]
        elif (isinstance(cur, list) and re.fullmatch(r"0|[1-9][0-9]*", token)
              and len(token) <= len(str(len(cur)))):
            index = int(token)
            if index >= len(cur):
                return _MISSING
            cur = cur[index]
        else:
            return _MISSING
    return cur if cur is not None else _MISSING


def _evidence_problem(ctx: _Ctx, row: _Row, raw: List[Any], *, health: bool
                      ) -> Tuple[Optional[str], Tuple[str, ...]]:
    """Validate the producer's evidence contract without reconstructing or repairing a reference."""
    rec = row.raw if isinstance(row.raw, dict) else {}
    limit = ENGINE_LIST_CAPS["health_scores[].deduction_refs"] if health else PUNCH_EVIDENCE_REFS_CAP
    if len(raw) > limit:
        return "the evidence list exceeds its producer's cap", ()
    hosts = [rec.get("switch")] if health else rec.get("devices")
    targets: List[str] = []
    for ref in raw:
        ok, value = _typed(ref, "evidence_ref")
        if not ok:
            return "a reference fails the closed engine evidence shape or vocabulary", ()
        if (PUNCH_EVIDENCE_RULES["host_must_be_row_device_or_null"] and value["host"] is not None
                and (not isinstance(hosts, list) or value["host"] not in hosts)):
            return "a reference names a device outside its producer row", ()
        if _evidence_target(ctx.s, value["ref"]) is _MISSING:
            return "an evidence pointer does not resolve to an observed value in this snapshot", ()
        section = value["ref"][1:].split("/", 1)[0].replace("~1", "/").replace("~0", "~")
        if section not in targets:
            targets.append(section)
    if health:
        deductions = rec.get("deductions")
        if not isinstance(deductions, list) or len(raw) > len(deductions):
            return "deduction_refs cannot be an ordered subsequence of the published deductions", tuple(targets)
    else:
        basis = rec.get("evidence_basis")
        if not _is_text(basis) or basis not in PUNCH_EVIDENCE_BASES:
            return "evidence_refs has no valid paired evidence_basis", tuple(targets)
        record = any(r["kind"] in PUNCH_EVIDENCE_RECORD_KINDS for r in raw)
        if ((PUNCH_EVIDENCE_RULES["absence_forbids_record_kinds"] and basis == "absence" and record)
                or (PUNCH_EVIDENCE_RULES["record_requires_record_kind"] and basis != "absence"
                    and (basis == "record") != record)
                or (PUNCH_EVIDENCE_RULES["row_requires_ref"] and basis == "row" and not raw)):
            return "evidence_basis contradicts the producer's reference rules", tuple(targets)
        if "evidence_refs_total" in rec and PUNCH_EVIDENCE_RULES["total_only_when_capped"]:
            ok, total = _count(rec["evidence_refs_total"])
            if type(rec["evidence_refs_total"]) is not int or not ok or len(raw) != limit or total <= limit:
                return "evidence_refs_total is valid only for a capped list with a larger integer total", tuple(targets)
    return None, tuple(targets)


def _evidence_list(ctx: _Ctx, row: _Row, *, health: bool = False,
                   capped: bool = False) -> Tuple[Dict[str, Any], Any]:
    field = "deduction_refs" if health else "evidence_refs"
    basis = (_B_HEALTH if health else _B_PUNCH) + field
    state, reason, toks, raw = _sub_list(
        ctx, row, field, pre_state=_not_scored(None, row) if health else None,
        empty=(_CBE, "collected but empty: the engine explicitly publishes no reference here; this does not "
                     "prove that no deduction or finding exists (not a blind spot)"))
    if (not health and state == _NC and isinstance(row.raw, dict) and "evidence_refs_total" in row.raw
            and "evidence_refs" not in row.raw):
        state, reason = _UV, "unverified: a reference total without its evidence list is malformed"
    targets = _evidence_sections(raw)
    if state in (_PUB, _CBE):
        hit = _secs_fail(ctx, targets)
        if hit:
            state, reason = hit
        else:
            problem, _ = _evidence_problem(ctx, row, raw, health=health)
            if problem:
                state, reason = _UV, "unverified: " + problem
    secs = tuple(dict.fromkeys(row.sections + targets))
    caveats = ("deduction_refs_are_subsequence",) if health else ()
    if capped or (not health and isinstance(raw, list) and len(raw) == PUNCH_EVIDENCE_REFS_CAP):
        caveats += ("engine_list_capped",)
    items = _items(ctx, toks, raw, "evidence_ref", basis + "[]", secs,
                   hold=(state, reason) if state not in (_PUB, _CBE) else None)
    return _listing(ctx, state, reason, toks, basis, items, sections=secs, extra=row.extra,
                    bare=row.bare, caveats=caveats), raw


def _evidence_sections(raw: Any) -> Tuple[str, ...]:
    """Section names from closed, syntactically valid refs, before failed producers' empty fallbacks resolve."""
    return tuple(dict.fromkeys(ref["ref"][1:].split("/", 1)[0].replace("~1", "/").replace("~0", "~")
                               for ref in (raw if isinstance(raw, list) else ())
                               if _typed(ref, "evidence_ref")[0]))


def _finding_evidence(ctx: _Ctx, row: _Row) -> Dict[str, Any]:
    listing, raw = _evidence_list(ctx, row)
    targets = _evidence_sections(raw)
    sections = tuple(dict.fromkeys(row.sections + targets))

    def basis_gate(_ctx: _Ctx, _typed: Any, _row: _Row):
        if listing["state"] not in (_PUB, _CBE):
            state = AU if listing["state"] == AU else _UV
            return state, listing.get("reason", "unverified: evidence_basis has no valid paired evidence_refs"), []
        return None

    basis = _cell(ctx, row, "evidence_basis", "enum", _B_PUNCH + "evidence_basis",
                  vocab=PUNCH_EVIDENCE_BASES, gate=basis_gate, sections=sections)

    def total_gate(_ctx: _Ctx, _typed: Any, _row: _Row):
        if listing["state"] not in (_PUB, _CBE):
            return listing["state"], listing.get("reason", _R_CBE), []
        return None

    total = _cell(ctx, row, "evidence_refs_total", "count", _B_PUNCH + "evidence_refs_total", gate=total_gate,
                  sections=sections,
                  missing="not collected: the engine publishes an uncapped reference total only when capped")
    readable = listing["state"] in (_PUB, _CBE)
    cap = {"limit": PUNCH_EVIDENCE_REFS_CAP,
           "reached": len(raw) == PUNCH_EVIDENCE_REFS_CAP if readable else None, "total": dict(total)}
    return {"evidence_basis": basis, "evidence_refs": listing, "evidence_refs_total": total,
            "evidence_refs_cap": cap}


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
    item.update(_finding_evidence(ctx, row))
    return item


def _findings(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("punchlist",)
    base, reason, raw = _list_state(ctx, toks, toks)
    cav = _brief_caveats(ctx)
    items = [_finding_row(ctx, i, rec, cav) for i, rec in enumerate(raw if isinstance(raw, list) else ())]
    mg = ("move_group_label_absent",) if ctx.mg_legacy else ()
    qualify = _fleet_qualify(ctx, config=True)
    legacy = ("punch_rows_carry_no_evidence_pointers",) if any(
        isinstance(rec, dict) and not {"evidence_refs", "evidence_basis", "evidence_refs_total"}.intersection(rec)
        for rec in (raw if isinstance(raw, list) else ())) else ()
    listing = _listing(ctx, base, reason, toks, "analyze.compute_migration_punchlist:punchlist", items, sections=toks,
                       rollup=PUNCHLIST_INPUTS, caveats=legacy + mg + cav,
                       qualify=qualify)
    total = _total(ctx, "punchlist", listing, sections=toks + PUNCHLIST_INPUTS,
                   caveats=legacy, qualify=qualify)
    axes = _get(ctx.s, ("executive_brief", "axes"))
    heads = [k for k, ax in enumerate(axes) if isinstance(ax, dict) and ax.get("axis") == "Migration punch-list"] \
        if isinstance(axes, list) else []
    return {"total": total, "headline_axis_index": heads[0] if len(heads) == 1 else None, "rows": listing,
            "facets": _finding_facets(ctx, listing, total, raw, qualify), "cross_layer": _cross_layer(ctx)}


# ---------------------------------------------------------------------------------------------------
# findings: facet totals (G21)
# ---------------------------------------------------------------------------------------------------
#: The facets the owner partitions, each with its closed vocabulary in owner order (the device facet is the G09 fold).
_OWNER_FACETS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (("severity", SEVERITIES), ("category", FINDING_CATEGORIES))
_B_FACET = "analyze.compute_punchlist_facets:stored punch-list rows by {facet}"
_B_DEVICE_FACET = ("analyze.compute_device_findings:stored punch-list rows by exact device.by_severity, summed "
                   "(each stored row once per named device)")
_R_FACET_EMPTY = ("collected but empty: the punch list carries no row, so no {facet} bucket holds a finding (not a "
                  "blind spot)")
_R_FACET_ZERO = ("not collected: no stored punch-list row has this {facet}, but the punch list may be incomplete, so "
                 "this zero is not a clean result: {why}")
_R_FACET_REFUSED = ("unverified: the engine's {facet} facet fold cannot place every stored punch-list row ({problem}), "
                    "so no {facet} count is published")
_R_FACET_UNRECONCILED = ("unverified: the engine's {facet} buckets do not place each of the {n} stored punch-list rows "
                         "exactly once, in the bucket its own {facet} names{total}, so no {facet} count is published")
_R_FACET_TOTAL = ("unverified: the punch list's row total is {state}, so the engine's {facet} buckets cannot be "
                  "reconciled with it and no {facet} count is published")
_B_DEVICE_FACETS = ("analyze.compute_device_findings:stored punch-list rows per inventory device (the devices map and "
                    "the collection_completeness blind spots)")
_R_SOURCE_NONE = ("unverified: the engine names no source section for the {category} findings "
                  "(analyze.PUNCH_CATEGORY_SECTION), so nothing says what this count was computed over")
_R_SOURCE_NC = ("not collected: {section}, the section the engine folds the {category} findings from, was not "
                "collected")
_R_SOURCE_AU = "{failed} ({section} is the section the engine folds the {category} findings from)"
_R_SOURCE_ZERO = "{why}, so a zero count of this category is not a clean result"
#: W51: a category source stored as a container other than its producer's (G21 P2).
_R_SOURCE_TYPE = ("unverified: {section}, the section the engine folds the {category} findings from, is present but is "
                  "not {kind}, and the engine's fold reads such a value as holding nothing, so it is not complete "
                  "evidence")
_R_SOURCE_NO_KIND = ("unverified: this projection registers no container type for {section}, the section the engine "
                     "folds the {category} findings from (CATEGORY_SOURCE_KINDS), so its stored value cannot be checked")
#: Each category source section (``analyze.PUNCH_CATEGORY_SECTION``'s values) -> the container its producer writes.
#: A source stored as anything else is no evidence (:func:`_category_sources`). tests/test_ui_projection_finding_facets.py
#: holds the key set equal to the owner map's sections and each type to the engine-built snapshots' stored sections.
CATEGORY_SOURCE_KINDS: Mapping[str, type] = MappingProxyType({
    **{section: list for section in ("cross_layer", "fhrp", "health_scores", "l3_forwarding", "link_phy",
                                     "operational_drift", "physical_health", "protocol_health", "trunk_native")},
    **{section: dict for section in ("addressing_conflicts", "config_hygiene", "device_dossiers", "devices",
                                     "ipv6_routing_adjacency_baseline", "multicast_intelligence", "platform_health",
                                     "qos_audit", "security", "service_map", "software_risk", "stp_roots",
                                     "syslog_intelligence", "vtp_safety_baseline")},
})
_R_SEVERITY_SOURCE_ZERO = ("{words}: no stored punch-list row has this severity, but a row of any category can carry "
                           "any severity, and these categories are folded from sections that are not complete evidence: "
                           "{detail}; so this zero is not a clean result")
#: A category source's withheld state, in the precedence a list rollup gives it (a failure, an owner fault, a blind
#: spot), with the words a reason opens with.
_SOURCE_HOLDS: Tuple[Tuple[str, str], ...] = ((AU, "analysis unavailable"), (_UV, "unverified"), (_NC, "not collected"))
#: ``(state, reason, ref entries)``: why a category's source section keeps its count from being complete.
_SourceHold = Tuple[str, str, List[Tuple[str, Sequence[Any]]]]


def _facet_refs(ctx: _Ctx, listing: Dict[str, Any]) -> List[Dict[str, str]]:
    """The punch list as the basis, then the row list's own witness and failure-record refs (its fleet
    qualifications and failed phases). The row list's subject and per-input basis refs stay on the list."""
    out = ctx.refs([("basis", ("punchlist",))])
    seen = {(ref["pointer"], ref["role"]) for ref in out}
    for ref in listing["refs"]:
        key = (ref["pointer"], ref["role"])
        if ref["role"] in ("witness", "failure_record") and key not in seen:
            seen.add(key)
            out.append({"pointer": ref["pointer"], "role": ref["role"]})
    return out


def _with_refs(ctx: _Ctx, refs: List[Dict[str, str]],
               entries: Sequence[Tuple[str, Sequence[Any]]]) -> List[Dict[str, str]]:
    """A fresh copy of `refs`, then each resolving entry it does not already carry."""
    out = [dict(ref) for ref in refs]
    seen = {(ref["pointer"], ref["role"]) for ref in out}
    for ref in ctx.refs(entries):
        if (ref["pointer"], ref["role"]) not in seen:
            seen.add((ref["pointer"], ref["role"]))
            out.append(ref)
    return out


def _category_sources(ctx: _Ctx) -> Dict[str, _SourceHold]:
    """Category -> its :data:`_SourceHold`, in owner order, for every category whose source section (the engine's
    ``analyze.PUNCH_CATEGORY_SECTION``) is not complete evidence for its count, first match wins: the section's phase
    failed (analysis_unavailable, with its failure records); the abstention core could not read it (unverified, with
    the owner fault); a failure the run recorded could not be attributed to sections -- an intermediate phase, a label
    nobody classified, or a failed-phase record that is not a list -- so it could have fed this section (W51:
    analysis_unavailable, with those failure records; the module's full failed-phase census, ``ssot.failed_sections``
    over ``ssot.PHASE_SECTIONS``, never only the one directly attributed failure); it was not collected
    (not_collected); or it is stored as a container other than its producer's (:data:`CATEGORY_SOURCE_KINDS`), which
    the engine's fold reads as holding nothing (unverified). The whole closed vocabulary is checked, never a hand list
    of sections, and a category the owner maps to no section, or to a section with no registered container, is
    unverified. A complete source is not listed. The held section is cited as a witness of the incompleteness, never
    as a basis: a lower bound over it stays published, and a basis ref to a failed section belongs only to a value
    that is itself unavailable."""
    out: Dict[str, _SourceHold] = {}
    for category in FINDING_CATEGORIES:
        section = PUNCH_CATEGORY_SECTION.get(category)
        if not _is_text(section):
            out[category] = (_UV, _R_SOURCE_NONE.format(category=category), [])
            continue
        token = ctx.abst(section)
        entries: List[Tuple[str, Sequence[Any]]] = [("witness", (section,))]
        kind = CATEGORY_SOURCE_KINDS.get(section)
        if token == AU or (token != _FAULT and ctx.unattributed):
            out[category] = (AU, _R_SOURCE_AU.format(failed=ctx.unavailable_reason((section,)), section=section,
                                                     category=category),
                             entries + ctx.failure_entries((section,), True))
        elif token == _FAULT:
            out[category] = (_UV, ctx.fault((section,)), entries)
        elif token == _NC:
            out[category] = (_NC, _R_SOURCE_NC.format(section=section, category=category), entries)
        elif kind is None:
            out[category] = (_UV, _R_SOURCE_NO_KIND.format(section=section, category=category), entries)
        elif not isinstance(ctx.s.get(section), kind):
            out[category] = (_UV, _R_SOURCE_TYPE.format(section=section, category=category, kind=_KIND[kind]),
                             entries)
    return out


def _severity_source_hold(sources: Mapping[str, _SourceHold]) -> Optional[_SourceHold]:
    """One hold for every severity bucket while any category source is incomplete: a row of any category can carry
    any severity. Its state is the strongest of the category holds (:data:`_SOURCE_HOLDS` order), its reason names
    each held category and section state, and its refs are all of theirs."""
    if not sources:
        return None
    states = {state for state, _why, _entries in sources.values()}
    state, words = next((s, w) for s, w in _SOURCE_HOLDS if s in states)
    named = dict(_SOURCE_HOLDS)
    labels = []
    for category, (held, _why, _entries) in sources.items():
        section = PUNCH_CATEGORY_SECTION.get(category)
        labels.append(f"{category} ({section} {named[held]})" if _is_text(section)
                      else f"{category} (no source section)")
    entries = [entry for _state, _why, held_entries in sources.values() for entry in held_entries]
    return state, _R_SEVERITY_SOURCE_ZERO.format(words=words, detail="; ".join(labels)), entries


def _facet_partition(ctx: _Ctx, facet: str, keys: Sequence[str], raw: Any,
                     total: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[Dict[str, List[int]]]]:
    """``(state, reason, buckets)`` for one owner facet over a published row list. The owner's buckets are
    admitted only as an exact partition: every key in owner order, every stored row placed exactly once in the
    bucket its own field names, and as many rows as the row list and its published total. A total that is not
    published leaves nothing to reconcile with, so the facet is withheld rather than checked against the rows
    alone. Anything else is unverified; a count is never repaired or recomputed here."""
    folded = ctx.punch_facets
    entry = folded.get(facet) if isinstance(folded, dict) else None
    if not isinstance(entry, dict):
        fault = ctx.faults.get("analyze.compute_punchlist_facets")
        return _UV, fault or _R_FACET_REFUSED.format(facet=facet, problem="unreadable owner output"), None
    problem, buckets = entry.get("problem"), entry.get("indices")
    if problem is not None or not isinstance(buckets, dict):
        why = problem if _is_text(problem) else "unreadable owner output"
        return _UV, _R_FACET_REFUSED.format(facet=facet, problem=why), None
    if total["state"] != _PUB:
        return _UV, _R_FACET_TOTAL.format(state=total["state"], facet=facet), None
    rows = raw if isinstance(raw, list) else []
    n_rows = len(rows)
    placed: List[Any] = []
    agrees = list(buckets) == list(keys)
    for key in keys if agrees else ():
        members = buckets.get(key)
        if not isinstance(members, list):
            agrees = False
            break
        placed.extend(members)
        agrees = all(type(index) is int and 0 <= index < n_rows and isinstance(rows[index], dict)
                     and rows[index].get(facet) == key for index in members)
        if not agrees:
            break
    stated = total["value"]
    if (not agrees or folded.get("n_rows") != n_rows or stated != n_rows
            or sorted(placed) != list(range(n_rows))):
        tail = f" (the published row total is {stated})" if stated != n_rows else ""
        return _UV, _R_FACET_UNRECONCILED.format(facet=facet, n=n_rows, total=tail), None
    return _PUB, None, buckets


def _device_facet(ctx: _Ctx, host: str) -> Dict[str, Any]:
    """One inventory device's finding count: its per-device rollup (G09, :func:`_device_finding_rollup`) summed
    over the closed severities. The rollup's state, reason and caveats are kept, so this count and the device's
    inventory row cannot disagree. Its refs are the rollup's basis, custody and qualification refs; the per-row
    witnesses (one per stored row naming the device) stay on the inventory row and the device page, so the facet
    grows with the roster, not with rows times devices."""
    counts = _device_finding_rollup(ctx, host)["by_severity"]
    refs = [{"pointer": ref["pointer"], "role": ref["role"]} for ref in counts["refs"]
            if not (ref["role"] == "witness" and ref["pointer"].startswith(json_pointer("punchlist") + "/"))]
    if counts["state"] != _PUB:
        return {"k": host, "n": _envelope(counts["state"], None, None, refs, _B_DEVICE_FACET, counts["reason"])}
    ok, value = _count(sum(counts["value"].values()))
    if not ok:
        return {"k": host, "n": _envelope(_UV, None, None, refs, _B_DEVICE_FACET, _unverified_reason("count"))}
    return {"k": host, "n": _envelope(_PUB, value, None, refs, _B_DEVICE_FACET, "",
                                      caveats=counts.get("caveats", ()))}


def _finding_facets(ctx: _Ctx, listing: Dict[str, Any], total: Dict[str, Any], raw: Any,
                    qualify: Sequence[_Qualify]) -> Dict[str, Any]:
    """G21: the punch-list row counts by severity, by category and by inventory device.

    The severity and category buckets are the owner's partition (``analyze.compute_punchlist_facets``), one per
    key of the owner's closed vocabulary, in its order. They follow the row list's final state: a missing punch
    list is not_collected, an empty one collected_but_empty, a failed or unreadable one withheld with the list's
    own reason. A published list is counted only through :func:`_facet_partition`.

    Two rules keep a count from claiming more than its evidence. A category is folded from one engine section
    (``analyze.PUNCH_CATEGORY_SECTION``, :func:`_category_sources`), which need not be a punch-list input: while that
    section failed, could not be read or was not collected, the category's positive count is a lower bound carrying
    ``finding_facet_source_incomplete`` with a ref to the section or its failure record, and its zero takes the
    section's state, never a clean result. A row of any category can carry any severity, so while any category's
    section is incomplete every severity bucket follows the same rule (:func:`_severity_source_hold`). Then, while a
    fleet qualification applies (blind devices, devices without a captured running-config), a positive count is a
    lower bound that carries the qualification's caveat and witnesses, and a zero is not_collected.

    The device facet is :func:`_device_facet` per inventory host, never a second fold, in a list that takes the
    roster's own state (:func:`_roster_list`): an absent or unreadable devices map is withheld, never an empty
    published roster."""
    state, reason = listing["state"], listing.get("reason")
    refs = _facet_refs(ctx, listing)
    caveats = tuple(cid for cid, _why, _wit in qualify) + _brief_caveats(ctx)
    why = "; ".join(text.removeprefix("not collected: ") for _cid, text, _wit in qualify)
    sources = _category_sources(ctx)
    severity_hold = _severity_source_hold(sources)
    holds: Dict[str, Dict[str, _SourceHold]] = {
        "severity": {key: severity_hold for key in SEVERITIES} if severity_hold else {},
        "category": {key: (held, _R_SOURCE_ZERO.format(why=held_why), entries)
                     for key, (held, held_why, entries) in sources.items()},
    }
    out: Dict[str, Any] = {}
    for facet, keys in _OWNER_FACETS:
        basis = _B_FACET.format(facet=facet)
        f_state, f_reason, buckets = state, reason, None
        if state == _CBE:
            f_reason = _R_FACET_EMPTY.format(facet=facet)
        elif state == _PUB:
            f_state, f_reason, buckets = _facet_partition(ctx, facet, keys, raw, total)
        if f_state != _PUB and not f_reason:
            f_reason = _state_reason(ctx, f_state, "count", ("punchlist",))
        facet_rows = []
        for key in keys:
            hold = holds[facet].get(key)
            if buckets is None:
                fact = _envelope(f_state, None, None, _with_refs(ctx, refs, ()), basis, f_reason or "")
            elif hold is not None:
                held, held_reason, entries = hold
                mine = _with_refs(ctx, refs, entries)
                if buckets[key]:
                    fact = _envelope(_PUB, len(buckets[key]), None, mine, basis, "",
                                     caveats=caveats + ("finding_facet_source_incomplete",))
                else:
                    fact = _envelope(held, None, None, mine, basis, held_reason)
            elif not buckets[key] and qualify:
                fact = _envelope(_NC, None, None, _with_refs(ctx, refs, ()), basis,
                                 _R_FACET_ZERO.format(facet=facet, why=why))
            else:
                fact = _envelope(_PUB, len(buckets[key]), None, _with_refs(ctx, refs, ()), basis, "",
                                 caveats=caveats)
            facet_rows.append({"k": key, "n": fact})
        out[facet] = facet_rows
    out["device"] = _roster_list(ctx, [_device_facet(ctx, host) for host in _inventory_universe(ctx)[0]],
                                 _B_DEVICE_FACETS, ("device_findings_scope",))
    return {facet: out[facet] for facet in FINDING_FACETS}


def project_findings(snap: Any) -> Dict[str, Any]:
    """The Findings screen: the engine's punch-list rows, with the remediation it links, their facet totals (G21: by
    severity, category and inventory device) under the same evidence states, and the engine's stored cross-layer
    correlation rows with the health deduction each one drives on each device it names (G24); nothing more."""
    return _findings(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# findings: cross-layer correlations (G24) and the health deduction each one drives
#
# Selected from the stored rows, never recomputed: the rows are analyze.compute_cross_layer_correlations' own, in its
# order. A host joins the devices map and its health_scores row by exact name. The deduction a row drives on a device
# is the one reference that device's health row publishes to the row (analyze.compute_health_scores writes it beside
# the line item, inside the same [:8] prefix), and the line item is the published deduction carrying the row's own
# '<id> <severity>' label. An unjoinable or repeated host, a missing or repeated reference and a missing line item are
# unverified with witnesses; a reference that may lie beyond the scorer's cut is not collected. Nothing is dropped.
# ---------------------------------------------------------------------------------------------------
#: The snapshot sections the cross-layer rules run over: the dependency map they read is built from the interface map
#: (its all_interfaces parameter), physical_health and l3_forwarding. tests/test_ui_projection_cross_layer.py holds
#: this table against the producer's signature.
CROSS_LAYER_INPUTS: Tuple[str, ...] = ("interfaces", "physical_health", "l3_forwarding")
_B_XL = "analyze.compute_cross_layer_correlations:cross_layer[]."
_B_XL_DEVICE = "ui_projection:exact devices-map hostname join"
_B_XL_REF = _B_HEALTH + "deduction_refs[] (the reference naming the cross-layer row)"
_B_XL_LINE = _B_HEALTH + "deductions[] (the line item carrying the cross-layer row's label)"
_R_XL_NO_HOSTS = ("unverified: analyze.compute_cross_layer_correlations names at least one device in every row, so a "
                  "row naming none cannot be read")
_R_XL_BLANK_HOST = "unverified: the host entry is blank, so it names no device"
_R_XL_HOST_DUP = ("unverified: this row names this host {n} times, but analyze.compute_cross_layer_correlations writes "
                  "each row's hosts once, so no single entry can be chosen")
_R_XL_NO_DEVICE = ("unverified: the devices map has no record with this exact name, yet the cross-layer rules name "
                   "only hosts of the collected interface model, so this host joins no collected device")
_R_XL_NO_HEALTH = ("unverified: health_scores has no row with this exact switch name, yet analyze.compute_health_scores "
                   "scores every named host of the interface model the cross-layer rules ran over, so the deduction "
                   "this row drives cannot be found")
_R_XL_REF_CAPPED = ("not collected: analyze.compute_health_scores cuts a device's deductions after {limit} and "
                    "publishes no total, and none of this device's published references names this row, so the "
                    "deduction it drives may lie beyond the cut")
_R_XL_REF_MISSING = ("unverified: this device's published deductions stop short of the scorer's cut of {limit}, yet "
                     "none of its references names this row; analyze.compute_health_scores writes one for every "
                     "device a cross-layer row names")
_R_XL_REF_AMBIG = ("unverified: {n} deduction references on this device name this row, but "
                   "analyze.compute_health_scores writes one for each row and device, so none can be chosen")
_R_XL_REF_FOREIGN = ("unverified: the deduction reference naming this row is not the scorer's analysis-row reference "
                     "for this device (kind analysis_row, role derived_from, this host)")
_R_XL_LINE_NONE = ("unverified: the deduction reference to this row lies inside the published deductions, yet no "
                   "published deduction carries the row's label '{label}', so its line item cannot be read")
_R_XL_LINE_DIFFER = ("unverified: {n} published deductions carry the row's label '{label}' with different points, so "
                     "no single line item can be read")
_R_XL_LINE_LABEL = "{word}: the row's {field} is withheld, so its deduction line item cannot be selected"
#: The kind and role analyze.compute_health_scores gives the reference from a deduction to the cross-layer row behind
#: it (its _evidence_ref("analysis_row", host, ("cross_layer", k), "derived_from", ...)).
_XL_REF_KIND, _XL_REF_ROLE = "analysis_row", "derived_from"
#: analyze.compute_health_scores' line item for a cross-layer row is f"{id} {severity}" then f" (-{points})": the
#: label is the row's own id and severity, the tail the points. Pinned to the real producer by
#: tests/test_ui_projection_cross_layer.py.
_XL_LINE_TAIL = r" \(-[0-9]+\)"


def _health_deductions(ctx: _Ctx, hrow: _Row) -> Tuple[str, Optional[str], Optional[Tuple[Any, ...]], Any, bool,
                                                      Dict[str, Any], Any]:
    """One health row's deduction prefix and its reference subsequence, read once by every surface that shows them
    (the device page and the cross-layer rows): ``(state, reason, toks, deductions, capped, refs listing, refs)``.
    The producer cuts both after its first eight deductions; reaching that cut is read from the deductions, never from
    the shorter reference subsequence."""
    dstate, dreason, dtoks, draw = _sub_list(
        ctx, hrow, "deductions", pre_state=_not_scored(None, hrow),
        empty=(_CBE, "collected but empty: the device was scored with no deduction (not a blind spot)"))
    capped = (dstate in (_PUB, _CBE) and isinstance(draw, list)
              and len(draw) >= ENGINE_LIST_CAPS["health_scores[].deductions"])
    refs, refs_raw = _evidence_list(ctx, hrow, health=True, capped=capped)
    return dstate, dreason, dtoks, draw, capped, refs, refs_raw


def _merged_refs(*groups: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Resolved refs from several envelopes, de-duplicated in order, as new containers."""
    out: List[Dict[str, str]] = []
    for group in groups:
        for ref in group:
            if ref not in out:
                out.append(dict(ref))
    return out


def _xl_device(ctx: _Ctx, host: str, host_toks: Tuple[Any, ...]) -> Dict[str, Any]:
    """The collected device a cross-layer host names: the devices-map record of exactly that name (its pointer), or
    why none can be joined. A blind spot is not collected; a name with no record is unverified, never dropped."""
    joined = _resolve(ctx, ("devices",), ("devices",), key=host, host=host, absent=(_UV, _R_XL_NO_DEVICE))
    entries: List[Tuple[str, Sequence[Any]]] = [("witness", host_toks)]
    if joined.state is not None:
        refs = ctx.refs(entries + ([("witness", joined.toks)] if joined.toks is not None else []) + joined.extra
                        + ctx.failure_entries(joined.sections, joined.state == AU))
        return _envelope(joined.state, None, None, refs, _B_XL_DEVICE, joined.reason or _R_NC)
    return _envelope(_PUB, json_pointer(*joined.toks), None, ctx.refs(entries + [("witness", joined.toks)]),
                     _B_XL_DEVICE, "")


def _xl_deduction(ctx: _Ctx, k: int, host: str, host_toks: Tuple[Any, ...], cells: Mapping[str, Dict[str, Any]],
                  cache: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``(deduction_ref, deduction)``: the health-row reference to cross_layer[k] on `host`, and the line item it
    sits beside. Selected, never derived: the reference by its exact pointer, the line item by the row's own label."""
    if host not in cache:
        hrow = _resolve(ctx, ("health_scores",), ("health_scores",), key=host, key_field="switch", host=host,
                        absent=(_UV, _R_XL_NO_HEALTH))
        cache[host] = (hrow, _health_deductions(ctx, hrow) if hrow.state is None else None)
    hrow, read = cache[host]
    secs = ("health_scores", "cross_layer")
    witness: List[Tuple[str, Sequence[Any]]] = [("witness", host_toks)]

    def withheld(state: str, reason: str, entries: Sequence[Tuple[str, Sequence[Any]]], basis: str,
                 extra: Sequence[Dict[str, str]] = (), caveats: Sequence[str] = ()) -> Dict[str, Any]:
        refs = _merged_refs(ctx.refs(witness + list(entries) + ctx.failure_entries(secs, state == AU)), extra)
        return _envelope(state, None, None, refs, basis, reason, caveats=caveats)

    def both(state: str, reason: str, entries: Sequence[Tuple[str, Sequence[Any]]],
             extra: Sequence[Dict[str, str]] = (), caveats: Sequence[str] = ()) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return (withheld(state, reason, entries, _B_XL_REF, extra, caveats),
                withheld(state, reason, entries, _B_XL_LINE, extra, caveats))

    if hrow.state is not None:
        return both(hrow.state, hrow.reason or _R_NC,
                    ([("witness", hrow.toks)] if hrow.toks is not None else []) + hrow.extra)
    _dstate, _dreason, dtoks, draw, capped, listing, refs_raw = read
    if listing["state"] not in (_PUB, _CBE):
        return both(listing["state"], listing.get("reason") or _R_NC, [("witness", hrow.toks)], listing["refs"])
    rtoks = hrow.toks + ("deduction_refs",)
    target = json_pointer("cross_layer", k)
    hits = [m for m, ref in enumerate(refs_raw if isinstance(refs_raw, list) else ())
            if isinstance(ref, dict) and ref.get("ref") == target]
    limit = ENGINE_LIST_CAPS["health_scores[].deductions"]
    if len(hits) > 1:
        return both(_UV, _R_XL_REF_AMBIG.format(n=len(hits)), [("witness", rtoks + (m,)) for m in hits])
    if not hits:
        if capped:
            return both(_NC, _R_XL_REF_CAPPED.format(limit=limit), [("witness", dtoks)],
                        caveats=("engine_list_capped",))
        return both(_UV, _R_XL_REF_MISSING.format(limit=limit), [("witness", rtoks)])
    m = hits[0]
    ref = refs_raw[m]
    if ref.get("host") != host or ref.get("kind") != _XL_REF_KIND or ref.get("role") != _XL_REF_ROLE:
        return both(_UV, _R_XL_REF_FOREIGN, [("witness", rtoks + (m,))])
    ref_fact = _cell(ctx, _Row(None, None, rtoks + (m,), ref, secs), None, "evidence_ref", _B_XL_REF,
                     witness=witness)
    if ref_fact["state"] != _PUB:
        return ref_fact, withheld(ref_fact["state"], ref_fact["reason"], [], _B_XL_LINE, ref_fact["refs"])
    on_ref: List[Tuple[str, Sequence[Any]]] = [("witness", rtoks + (m,))]
    for field in ("id", "severity"):
        cell = cells[field]
        if cell["state"] != _PUB:
            state = cell["state"] if cell["state"] in (AU, _NC) else _UV
            word = impact_assessability.STATE_WORD[state]          # the owner's word per withheld state (W33)
            return ref_fact, withheld(state, _R_XL_LINE_LABEL.format(word=word, field=field),
                                      on_ref + [("witness", ("cross_layer", k, field))], _B_XL_LINE)
    label = f"{cells['id']['value']} {cells['severity']['value']}"
    pattern = re.compile(re.escape(label) + _XL_LINE_TAIL)
    lines = [n for n, text in enumerate(draw if isinstance(draw, list) else ())
             if _is_text(text) and pattern.fullmatch(text)]
    if not lines:
        return ref_fact, withheld(_UV, _R_XL_LINE_NONE.format(label=label), on_ref + [("witness", dtoks)],
                                  _B_XL_LINE)
    if len({draw[n] for n in lines}) > 1:
        return ref_fact, withheld(_UV, _R_XL_LINE_DIFFER.format(n=len(lines), label=label),
                                  on_ref + [("witness", dtoks + (n,)) for n in lines], _B_XL_LINE)
    cav = ("row_selection_by_exact_key",)
    if len(lines) == 1:
        return ref_fact, _cell(ctx, _Row(None, None, dtoks + (lines[0],), draw[lines[0]], secs), None, "text",
                               _B_XL_LINE, witness=on_ref, published_caveats=cav)
    # Several rows of one rule and severity name this device: their line items are byte-identical, so the value is
    # this row's, but which position is its own is not published -- one value, a witness to each, no subject.
    refs = ctx.refs([("witness", dtoks + (n,)) for n in lines] + on_ref)
    return ref_fact, _envelope(_PUB, draw[lines[0]], None, refs, _B_XL_LINE, "",
                               caveats=cav + _one_hop(ctx, _PUB, secs))


def _xl_host(ctx: _Ctx, k: int, j: int, raw: Any, positions: Mapping[str, List[int]],
             hold: Optional[Tuple[str, Optional[str]]], cells: Mapping[str, Dict[str, Any]],
             cache: Dict[str, Any]) -> Dict[str, Any]:
    """One host a cross-layer row names, with the collected device it joins and the deduction the row drives there.
    A host that cannot be read or is named twice withholds its joins with its own state, reason and witnesses.
    `positions` maps each text host of the row to every index naming it."""
    toks = ("cross_layer", k, "hosts", j)
    same = positions.get(raw, []) if _is_text(raw) else []
    doubt: Optional[_Withheld] = None
    if len(same) > 1:
        doubt = (_UV, _R_XL_HOST_DUP.format(n=len(same)), [("witness", ("cross_layer", k, "hosts", i)) for i in same])
    row = _Row(hold[0] if hold else None, hold[1] if hold else None, toks, raw, ("cross_layer",))
    fact = _cell(ctx, row, None, "text", _B_XL + "hosts[]",
                 pre=(lambda _raw, _row: doubt) if doubt is not None else None, empty=(_UV, _R_XL_BLANK_HOST))
    item: Dict[str, Any] = {"index": j, "pointer": json_pointer(*toks), "host": fact}
    if fact["state"] == _PUB:
        item["device"] = _xl_device(ctx, raw, toks)
        item["deduction_ref"], item["deduction"] = _xl_deduction(ctx, k, raw, toks, cells, cache)
        return item
    for name, basis in (("device", _B_XL_DEVICE), ("deduction_ref", _B_XL_REF), ("deduction", _B_XL_LINE)):
        item[name] = _envelope(fact["state"], None, None, _merged_refs(fact["refs"]), basis, fact["reason"])
    return item


def _cross_layer_row(ctx: _Ctx, k: int, rec: Any, cache: Dict[str, Any]) -> Dict[str, Any]:
    toks = ("cross_layer", k)
    row = _list_row(toks, rec, ("cross_layer",))
    cells: Dict[str, Dict[str, Any]] = {
        "id": _cell(ctx, row, "id", "text", _B_XL + "id"),
        "severity": _cell(ctx, row, "severity", "enum", _B_XL + "severity", vocab=SEVERITIES),
    }
    for field in ("layers", "title", "detail", "recommendation"):
        cells[field] = _cell(ctx, row, field, "text", _B_XL + field)
    state, reason, htoks, hosts = _sub_list(ctx, row, "hosts", empty=(_UV, _R_XL_NO_HOSTS))
    hold = (state, reason) if state not in (_PUB, _CBE) else None
    named = hosts if isinstance(hosts, list) else []
    positions: Dict[str, List[int]] = {}
    for j, raw in enumerate(named):
        if _is_text(raw):
            positions.setdefault(raw, []).append(j)
    items = [_xl_host(ctx, k, j, raw, positions, hold, cells, cache) for j, raw in enumerate(named)]
    listing = _listing(ctx, state, reason, htoks, _B_XL + "hosts", items, sections=row.sections, extra=row.extra,
                       caveats=("row_selection_by_exact_key",))
    return {"index": k, "pointer": json_pointer(*toks), **cells, "hosts": listing}


def _cross_layer(ctx: _Ctx) -> Dict[str, Any]:
    """``findings.cross_layer``: every stored cross-layer row, in the producer's order, with its hosts joined. The rules
    run over every collected device's evidence, so the fleet's blind spots qualify the list (an empty one under a blind
    spot is not collected, never 'no correlation')."""
    toks = ("cross_layer",)
    base, reason, raw = _list_state(ctx, toks, toks)
    cache: Dict[str, Any] = {}
    items = [_cross_layer_row(ctx, k, rec, cache) for k, rec in enumerate(raw if isinstance(raw, list) else ())]
    return _listing(ctx, base, reason, toks, "analyze.compute_cross_layer_correlations:cross_layer", items,
                    sections=toks, rollup=CROSS_LAYER_INPUTS, qualify=_fleet_qualify(ctx))


# ---------------------------------------------------------------------------------------------------
# the device page (a standalone document per device)
# ---------------------------------------------------------------------------------------------------
_B_IF = "html.snapshot_state:interfaces{}{}."
_B_SEC = "parse.parse_security:security{}."
_B_RP = "analyze.compute_remediation_plan:remediation_plan.by_device{}[]."
_B_NRFU = "nrfu_export.compute_nrfu_commands:nrfu_commands.waves[].devices[].cases[]."
#: compute_failure_impact writes one row per host of build_network_model (every scanned host). A device with no row
#: was not simulated: its absence is a blind spot, never "no impact".
_ABSENT_IMPACT = (_NC, "not collected: the failure-impact simulation (analyze.compute_failure_impact) carries no row "
                       "for this device, so it was not simulated; an absent row is not 'no impact'")
#: compute_link_centrality keeps only CDP/LLDP links whose two ends are both scanned hosts (_topology_adjacency), so a
#: device can be absent for reasons other than having no inter-switch link.
_ABSENT_STRUCTURAL = (_NC, "not collected: no structural link names this device. The scanned host-pair model "
                           "(analyze.compute_link_centrality) keeps only CDP/LLDP links whose two ends were both "
                           "scanned, so an absent row can mean an unscanned or uncollected peer, or CDP/LLDP evidence "
                           "that was not captured or parsed; it is not proof that the device has no inter-switch link")


def _nrfu_marker(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_SENTINEL) if raw == NRFU_NOT_OBSERVED else None


def _roc_false(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, "not collected: the record does not say the running-config was observed for this port") \
        if raw is False else None


def _interfaces_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
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


def _selection_rows(ctx: _Ctx, host: Any, forced: Optional[_Forced], block: str, toks: Tuple[str, ...],
                    fields: Tuple[str, ...], basis: str, cbe: Union[str, Tuple[str, str]],
                    build: Callable[[int, Any], Dict[str, Any]], *,
                    multi: bool = False, base_state: Optional[Tuple[str, Optional[str], Any]] = None,
                    sections: Optional[Tuple[str, ...]] = None, config: bool = False,
                    unique: bool = False, qualify: Sequence[_Qualify] = ()) -> Dict[str, Any]:
    """The rows of one engine list that name this device (selection only; never a count). The device's own gaps
    (:func:`_device_gap` over the captures :data:`SELECTION_NEEDS` names for `block`) make it not_collected. With
    `unique` the producer writes at most one row per device, so two rows naming it are unverified (never picked
    between). Every selection follows the one key-join rule of :func:`_resolve`: a row the exact-key join cannot read
    (:func:`_unjoinable_rows`, with `multi` a key list holding anything but text too) could name this device, so the
    selection is unverified with a witness to each such row (the fleet list withholds that row's key too), and so is
    a selection whose device scope cannot say the device is not a blind spot (:meth:`_Ctx.device_scope`). Each doubt
    also carries the device's own gap and its witnesses. `qualify` (:func:`_fleet_qualify`) carries the fleet's blind
    spots onto a selection whose rows other devices' evidence shapes; `cbe` is as in :func:`_sel_state`."""
    secs = sections or (toks[0],)
    if forced is not None:
        return _listing(ctx, forced[0], forced[1], None, basis, [], extra=_forced_wit(forced), bare=True)
    base, reason, raw = base_state or _list_state(ctx, toks, (toks[0],))
    sel = ctx.index(toks, fields, multi).get(host, []) if isinstance(raw, list) and _is_text(host) else []
    items = [build(i, raw[i]) for i in sel]
    gap = _device_gap(ctx, host, toks[0], SELECTION_NEEDS[block], config=config)
    doubts: List[str] = []
    wit: List[Tuple[str, Sequence[Any]]] = []
    # An unverified list whose rows can still be read (the abstention core calls it empty because every row is
    # deep-empty, or an owner faulted) keeps its own reason; an unreadable member is witnessed there too.
    if base in (_PUB, _CBE) or (base == _UV and isinstance(raw, list)):
        if unique and len(sel) > 1:
            doubts.append(_R_AMBIG.format(n=len(sel), section=".".join(toks)))
            wit += [("witness", toks + (i,)) for i in sel]
        bad = ctx.unjoinable(toks, fields, multi)            # raw is the list at toks here
        if bad:
            doubts.append(_R_UNJOINABLE.format(n=len(bad), section=".".join(toks)))
            wit += [("witness", toks + (i,)) for i in bad]
        scope = ctx.device_scope(toks[0], host)
        if scope is not None and scope[0] == _UV:
            doubts.append(scope[1])
            wit += scope[2]
    if doubts:
        head = [reason] if base == _UV and reason else []
        state, reason = _UV, "; ".join(head + doubts) + (f"; the device also has a collection gap: {gap[0]}"
                                                         if gap is not None else "")
        wit += gap[1] if gap is not None else []
    else:
        state, reason, wit = _sel_state(ctx, base, reason, sel, gap, cbe, unique=unique)
    return _listing(ctx, state, reason, toks, basis, items, sections=secs, extra=wit,
                    caveats=("row_selection_by_exact_key",), qualify=qualify)


def _unjoinable_rows(raw: Any, fields: Tuple[str, ...], multi: bool = False) -> List[int]:
    """The rows of a list an exact-key join over text `fields` cannot read: not an object, or a key field that is
    missing or not text (with `multi`, a field may also be a list of keys, as :meth:`_Ctx.index` reads it, and a list
    holding anything but text cannot be read in full). :meth:`_Ctx.index` skips them, so any of them could name the
    device being joined."""
    def readable(value: Any) -> bool:
        return _is_text(value) or (multi and isinstance(value, list) and all(_is_text(x) for x in value))

    return [i for i, row in enumerate(raw if isinstance(raw, list) else ())
            if not (isinstance(row, dict) and all(readable(row.get(f)) for f in fields))]


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


def _routes_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
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


def _neighbors_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
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
                rows.append({"index": i, "pointer": json_pointer(*toks), **cells,
                             "peer_host": _peer_host(ctx, host, proto, toks, cells)})
        groups.append({"protocol": proto, "pointer": json_pointer(*gtoks),
                       "neighbors": _listing(ctx, state, reason, gtoks, group_basis, rows,
                                             sections=("routing_neighbors",),
                                             caveats=("routing_neighbors_empty_is_ambiguous",))})
    state, reason = (rn.state, rn.reason) if rn.state else (
        (_PUB, None) if groups else (_NC, "not collected: the engine recorded no routing protocol for this device"))
    return _listing(ctx, state, reason, rn.toks, "build.build_routing_neighbors:routing_neighbors{}", groups,
                    sections=("routing_neighbors",), extra=rn.extra, bare=rn.bare,
                    caveats=("routing_neighbors_empty_is_ambiguous",))


def _security_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
    sr = _resolve(ctx, ("security",), ("security",), key=host, host=host, forced=forced,
                  absent=(_NC, "not collected: security carries no row for this device (no captured running-config)"))
    state, reason, toks, raw = _sub_list(ctx, sr, "findings", empty=(_CBE, "collected but empty: the check list is "
                                                                           "empty (not a blind spot)"))
    checks = _listing(ctx, state, reason, toks, _B_SEC + "findings", _items(ctx, toks, raw, "security_check",
                                                                               _B_SEC + "findings[]", ("security",)),
                      sections=("security",), extra=sr.extra, bare=sr.bare)
    return {"summary": _cell(ctx, sr, "summary", "security_summary", _B_SEC + "summary"), "checks": checks}


def _remediation_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
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
        item["wave"] = _cell(ctx, row, "wave", "text", _B_RP + "wave", sections=mg_secs, pre=_mg_pre(ctx, host=host),
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
                              caveats=(("move_group_label_absent",) if ctx.mg_legacy else ()))}


def _nrfu_block(ctx: _Ctx, host: Any, forced: Optional[_Forced]) -> Dict[str, Any]:
    toks = ("nrfu_commands", "waves")
    basis = "nrfu_export.compute_nrfu_commands:nrfu_commands.waves[].devices[].cases"
    if forced is not None:
        return _listing(ctx, forced[0], forced[1], None, basis, [], extra=_forced_wit(forced), bare=True)
    scope = ctx.device_scope("nrfu_commands", host)
    if scope is not None and scope[0] == _NC:
        return _listing(ctx, _NC, scope[1], toks, basis, [], sections=("nrfu_commands",), extra=scope[2])
    base, reason, raw = _list_state(ctx, toks, ("nrfu_commands",))
    items: List[Dict[str, Any]] = []
    malformed = False
    lost: List[Tuple[Any, ...]] = []        # device entries the exact host join cannot read (_unjoinable_rows)
    for w, wave in enumerate(raw if isinstance(raw, list) else ()):
        devs = wave.get("devices") if isinstance(wave, dict) else None
        if not isinstance(devs, list):
            malformed = True
            continue
        wtoks = toks + (w, "devices")       # raw is the list at toks, so devs is the list at wtoks
        lost += [wtoks + (d,) for d in ctx.unjoinable(wtoks, ("host",))]
        for d in (ctx.index(wtoks, ("host",)).get(host, []) if _is_text(host) else []):
            dev = devs[d]
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
    extra: List[Tuple[str, Sequence[Any]]] = []
    if base in (_PUB, _CBE):
        doubts = (["unverified: an NRFU wave or device entry is malformed, so its cases cannot be read"]
                  if malformed else [])
        if lost:
            doubts.append(_R_UNJOINABLE.format(n=len(lost), section="nrfu_commands.waves[].devices"))
            extra += [("witness", t) for t in lost]
        if scope is not None:
            doubts.append(scope[1])
            extra += scope[2]
        if doubts:
            base, reason = _UV, "; ".join(doubts)
        else:
            base, reason = (_PUB, None) if items else (_NC, "not collected: the NRFU pack generated no case for this "
                                                            "device")
    return _listing(ctx, base, reason, toks, basis, items, sections=("nrfu_commands",), extra=extra)


def _device_limitations_payload() -> List[Dict[str, Any]]:
    """The device document's own limitations, then every payload limitation a device page can cite, re-addressed."""
    return [{"id": lim["id"], "owner": lim["owner"], "text": lim["text"], "applies_to": list(lim["applies_to"])}
            for lim in _DEVICE_DOC_LIMITATIONS]


#: The rosters a device page joins a text host to, with the type each is written as: the devices map, the blind-spot
#: list (by its owner's device-scope rule) and the cable-map nodes.
_ROSTERS: Tuple[Tuple[Tuple[str, ...], type], ...] = (
    (("devices",), dict), (_CC_ROWS, list), (("cable_map", "nodes"), list))


def _roster_join(ctx: _Ctx, host: str) -> Tuple[Dict[str, bool], Optional[Tuple[Any, ...]]]:
    """Which rosters name the text `host`, and the forced state of a page no roster names. The rosters are key joins
    too, held to the one rule (:func:`_resolve`): a roster row a join cannot read, or a roster the snapshot carries as
    the wrong type, could name this host, so a host no readable roster names is then ``unverified``, with a witness to
    each such row or roster (:func:`_forced_wit`), never the clean "no roster names this device". ``None``: a roster
    names it, and the page is joined row by row."""
    devices = ctx.s.get("devices")
    rosters = {"devices": isinstance(devices, dict) and host in devices,
               "collection_completeness": ctx.cc_row(host)[0] is not None,
               "cable_map": host in ctx.index(("cable_map", "nodes"), ("host",))}
    if any(rosters.values()):
        return rosters, None
    parts: List[str] = []
    wit: List[Tuple[str, Sequence[Any]]] = []
    for toks, want in _ROSTERS:
        where = _unreadable_container(ctx.s, toks, want)
        if where is not None:
            parts.append(_R_ROSTER_UNREADABLE.format(path=".".join(where[0]), kind=_KIND[where[1]]))
            wit.append(("witness", where[0]))
    lost = ([_CC_ROWS + (i,) for i in ctx.unjoinable(_CC_ROWS, ("host",))]
            + [("cable_map", "nodes", i) for i in ctx.unjoinable(("cable_map", "nodes"), ("host",))])
    if lost:
        parts.append(_R_ROSTER_UNJOINABLE.format(n=len(lost)))
        wit += [("witness", t) for t in lost]
    if not parts:
        return rosters, (_NC, _R_UNKNOWN_HOST)
    return rosters, (_UV, _R_UNKNOWN_HOST_DOUBT.format(parts="; ".join(parts)), wit)


def _device_page(ctx: _Ctx, host: Any) -> Dict[str, Any]:
    if _is_text(host):
        rosters, forced = _roster_join(ctx, host)
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
    # One reading of the deduction prefix and its references, shared with the cross-layer rows (_xl_deduction).
    dstate, dreason, dtoks, draw, ded_capped, deduction_refs, _ = _health_deductions(ctx, hrow)
    ded_readable = dstate in (_PUB, _CBE)
    deductions = _listing(ctx, dstate, dreason, dtoks, _B_HEALTH + "deductions",
                          _items(ctx, dtoks, draw, "text", _B_HEALTH + "deductions[]", ("health_scores",),
                                 hold=(dstate, dreason) if dstate == _NA else None),
                          sections=("health_scores",), extra=hrow.extra, bare=hrow.bare,
                          caveats=("engine_list_capped",) if ded_capped else ())
    # The cap bounds the deduction prefix BEFORE unaddressable refs are removed. Reaching it is
    # determined from deductions, never from the shorter reference subsequence.
    deduction_refs_cap = _cap(ded_cap, draw, "analyze.compute_health_scores",
                              ded_readable and deduction_refs["state"] in (_PUB, _CBE))
    lc = j["lifecycle"]
    dated = _blank("not collected: the engine publishes no date here (it withholds the EoS / LDoS dates when no "
                   "retained bulletin matches the model)")
    dd = j["dossier"]
    xs, xr, xt, xraw = _sub_list(ctx, dd, "exposures", empty=(_CBE, "collected but empty: the dossier lists no "
                                                                    "exposure axis (not a blind spot)"))
    cs, cr, ct, craw = _sub_list(ctx, dd, "compound", empty=(_CBE, "collected but empty: no compound risk pattern "
                                                                   "coincides on this device (not a blind spot)"))
    cov = _coverage_scope(ctx, host, forced)
    cov_items: List[Dict[str, Any]] = []
    for axis in (sorted(k for k in cov.raw if _is_text(k)) if cov.state is None else ()):
        crow = _Row(None, None, cov.toks + (axis,), cov.raw[axis], ("coverage_matrix",))
        joined = _coverage_join(ctx, cov, host, axis)
        if joined.state is not None:
            crow = _Row(joined.state, joined.reason, crow.toks, None, crow.sections, joined.extra)
        fact = _cell(ctx, crow, None, "coverage_cell", "coverage_matrix.compute_coverage_matrix:by_device{}{}",
                     witness=joined.extra, published_caveats=("coverage_matrix_shown_as_published",))
        if fact["state"] == _PUB:
            fact["value"] = {"axis": axis, "state": fact["value"]}
        cav = ("coverage_matrix_shown_as_published",)
        basis = "coverage_matrix.compute_coverage_matrix:rows[]."
        cov_items.append({
            "axis": axis, "pointer": json_pointer(*crow.toks), "fact": fact,
            "dimension": _cell(ctx, joined, "dimension", "enum", basis + "dimension",
                               vocab=COVERAGE_DIMENSIONS, published_caveats=cav),
            "verdict_source": _cell(ctx, joined, "verdict_source", "enum", basis + "verdict_source",
                                    vocab=COVERAGE_VERDICT_SOURCES, published_caveats=cav),
            "is_abstention": _cell(ctx, joined, "is_abstention", "flag", basis + "is_abstention",
                                   published_caveats=cav),
        })
    cov_state, cov_reason = (cov.state, cov.reason) if cov.state else (_PUB if cov_items else _CBE, None)
    punch_base, punch_reason, _praw = _list_state(ctx, ("punchlist",), ("punchlist",))
    punch_state = _rolled(ctx, punch_base, punch_reason, ("punchlist",), PUNCHLIST_INPUTS)
    return {
        "host": host if _is_text(host) else None,
        "rosters": rosters,
        "move_group": _move_group_fact(ctx, host, forced),
        "findings_rollup": _device_finding_rollup(ctx, host, forced),
        "coverage_rollup": _device_coverage_rollup(ctx, host, forced),
        "identity": {f: _cell(ctx, dev, f, "text", _dev_basis(f), pre=_default_text) for f in IDENTITY_FIELDS},
        "physical": physical,
        "collection": {"status": _cell(ctx, cc, "status", "enum", _B_CC + "status", vocab=CC_STATUSES),
                       "data_quality": _cell(ctx, cc, "data_quality", "score", _B_CC + "data_quality"),
                       "missing": _cell(ctx, cc, "missing", "text_list", _B_CC + "missing")},
        "health": {**health, "deductions": deductions,
                   "deduction_refs": deduction_refs, "deduction_refs_cap": deduction_refs_cap,
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
        # G10/G11: the stored fleet rows naming this device, built by the fleet topology's own row builders. Both
        # producers compute over every scanned device's evidence, so the fleet's blind spots qualify them (as on the
        # fleet topology lists). A device whose own gateway SVIs never reached the simulation (no scoped interface
        # running-config) is held inside its row by the shared builder (the engine owner's
        # impact_assessability.row_hold), never by a second selection gap: the fleet row and this page show one state.
        "failure_impact": _selection_rows(
            ctx, host, forced, "failure_impact", ("failure_impact",), ("host",),
            "analyze.compute_failure_impact:failure_impact", _ABSENT_IMPACT,
            lambda i, rec: _topology_impact(ctx, i, rec), unique=True, qualify=_fleet_qualify(ctx)),
        "structural_links": _selection_rows(
            ctx, host, forced, "structural_links", ("link_centrality",), ("a_host", "b_host"),
            "analyze.compute_link_centrality:link_centrality", _ABSENT_STRUCTURAL,
            lambda i, rec: _topology_structural(ctx, i, rec), qualify=_fleet_qualify(ctx)),
        "limitations": _device_limitations_payload(),
    }


def project_device(snap: Any, host: Any) -> Dict[str, Any]:
    """One device page, as a standalone ``DeviceDocument``: identity, physical, blind-spot record, health,
    lifecycle, dossier, coverage, interfaces, links, routes, routing neighbours (each with its ``peer_host``: the one
    collected device the topology's address index places the neighbour's address on, G17), security checks, native-VLAN
    mismatches, remediation, NRFU cases, the punch-list rows and endpoints that name it, and the stored
    failure-impact row (``failure_impact``) and structural-link rows (``structural_links``, either end) that name it.
    Those two are the fleet topology rows selected by exact host, never re-simulated; an empty selection is
    not_collected, never "no impact" or "no link". A host no roster names claims nothing; a host that is not a
    string names no row."""
    ctx = _Ctx(snap)
    return {"schema": SCHEMA, "engine": _engine(ctx), "device": _device_page(ctx, host), "vocab": _vocab()}


def project_devices(snap: Any, hosts: Any) -> List[Dict[str, Any]]:
    """One ``DeviceDocument`` per host in `hosts` (a list or tuple; anything else names none), in order, over ONE
    shared context: each document equals :func:`project_device` for its host and owns every container in it."""
    ctx = _Ctx(snap)
    return [{"schema": SCHEMA, "engine": _engine(ctx), "device": _device_page(ctx, host), "vocab": _vocab()}
            for host in (hosts if isinstance(hosts, (list, tuple)) else ())]


def _topology_legend() -> Dict[str, Any]:
    """Presentation vocabulary owned here; browser themes only choose colors for the supplied tone."""
    meanings = (
        "Observed record; not a health assurance", "Peer was not collected", "Evidence cannot be verified",
        "Evidence was not observed", "Required analysis was unavailable", "Reported link up", "Reported link down",
        "Link state unknown", "Scanned host-pair link", "Bridge in the scanned host-pair graph",
        "High modelled failure impact", "Medium modelled failure impact", "Low modelled failure impact",
        "Informational modelled impact; not a health assurance", "Route model reached destination",
        "Route model has a reaching path and dropping ECMP legs", "Route model observed discard",
        "No route in the captured scope; not an observed discard", "Route model is a lower bound",
        "Path calculation withheld",
    )
    entries = []
    for token, meaning in zip(TOPOLOGY_STYLE_TOKENS, meanings):
        tone, stroke, weight = "neutral", "solid", "normal"
        if token in ("observed", "link_up", "path_reached"):
            tone = "info"
        elif token in ("uncollected", "not_observed", "link_unknown"):
            tone, stroke = "muted", "dotted"
        elif token in ("unverified", AU, "path_withheld"):
            tone, stroke = "warning", "dashed"
        elif token in ("link_down", "impact_high", "path_observed_discard"):
            tone = "danger"
        elif token in ("structural_bridge", "path_partial_drop", "impact_medium",
                       "path_no_route_observed", "path_lower_bound"):
            tone = "warning"
        if token in ("structural_bridge", "impact_high", "path_observed_discard"):
            weight = "strong"
        entries.append({"token": token, "tone": tone, "stroke": stroke, "weight": weight, "meaning": meaning})
    return {"schema": TOPOLOGY_STYLE_SCHEMA, "entries": entries,
            "fallback": {"token": "unverified", "glyph": "unknown", "label": "Evidence cannot be verified"}}


def _topology_style(facts: Sequence[Dict[str, Any]], token: str, *, glyph: str = "none") -> Dict[str, Any]:
    """The style describes even a withheld observation, but never supplies its missing value."""
    states = {fact["state"] for fact in facts}
    if AU in states:
        token = AU
    elif _UV in states:
        token = "unverified"
    elif states - {_PUB}:
        token = "not_observed"
    refs = []
    for fact in facts:
        for ref in fact["refs"]:
            if ref not in refs:
                refs.append(dict(ref))
    meaning = next(entry["meaning"] for entry in _topology_legend()["entries"] if entry["token"] == token)
    return _envelope(_PUB, {"token": token, "glyph": glyph, "label": meaning}, None, refs,
                     "ui_projection.topology_style/1", "", caveats=("topology_scanned_model",))


#: A value withheld with the cell it comes from: ``(state, reason, witness ref entries)``.
_Withheld = Tuple[str, str, List[Tuple[str, Sequence[Any]]]]


def _topology_join(ctx: _Ctx, host: Any, withheld: Optional[_Withheld] = None) -> Dict[str, Any]:
    """The cable-map nodes with exactly this hostname. With `withheld` the endpoint is withheld with its cell (that
    state, reason and those witnesses), so no node is joined for a value the row does not publish. The join follows
    the one key-join rule of :func:`_resolve`: a node row it cannot read (:func:`_unjoinable_rows`) could carry this
    hostname, so beside one the join is unverified, with a witness to it and to each node that does carry the name:
    never a single node picked, and never the clean absence "no node has this hostname"."""
    toks = ("cable_map", "nodes")
    state, reason, raw = _topology_source(ctx, toks)
    indices = []
    wit: List[Tuple[str, Sequence[Any]]] = []
    if withheld is not None:
        if state in (_PUB, _CBE):
            state, reason, wit = withheld[0], withheld[1], list(withheld[2])
    else:
        bad: List[int] = []
        if isinstance(raw, list) and _is_text(host) and host:
            indices = ctx.index(toks, ("host",)).get(host, [])
            bad = ctx.unjoinable(toks, ("host",))
        doubted = False
        if state in (_PUB, _CBE):
            if not _is_text(host) or not host:
                state, reason = _UV, "unverified: the endpoint has no nonempty exact hostname"
            elif bad:
                doubted = True
                state, reason = _UV, "; ".join(
                    (["unverified: more than one node has this exact hostname"] if len(indices) > 1 else [])
                    + [_R_UNJOINABLE.format(n=len(bad), section="cable_map.nodes")])
            elif len(indices) > 1:
                state, reason = _UV, "unverified: more than one node has this exact hostname"
            elif not indices:
                state, reason = _NC, "not collected: no cable-map node has this exact hostname"
            else:
                state = _PUB
        wit = [("witness", toks + (i,)) for i in indices + (bad if doubted else [])]
    return _listing(ctx, state, reason, toks, "ui_projection:exact cable-map hostname join",
                    [{"index": i, "pointer": json_pointer(*toks, i)} for i in indices], sections=("cable_map",),
                    extra=wit, caveats=("topology_scanned_model",))


def _topology_node(ctx: _Ctx, i: int, raw: Any) -> Dict[str, Any]:
    row = _list_row(("cable_map", "nodes", i), raw, ("cable_map",))
    basis = "analyze.compute_cable_map:cable_map.nodes[]."
    out = {"index": i, "pointer": json_pointer(*row.toks)}
    for field in ("host", "kind", "role", "collected"):
        out[field] = _cell(ctx, row, field, "flag" if field == "collected" else "text", basis + field,
                           pre=None if field == "collected" else _blank("not collected: the node has no observed " + field),
                           caveats=("topology_scanned_model",))
    glyph = out["kind"]["value"] if out["kind"]["value"] in TOPOLOGY_GLYPHS[:-1] else "unknown"
    out["style"] = _topology_style([out["host"], out["kind"], out["collected"]],
                                    "observed" if out["collected"]["value"] else "uncollected", glyph=glyph)
    return out


def _topology_cable(ctx: _Ctx, i: int, raw: Any) -> Dict[str, Any]:
    out = _cable_row(ctx, i, raw)
    row = _list_row(("cable_map", "cables", i), raw, ("cable_map",))
    state, reason, toks, members = _sub_list(ctx, row, "members")
    items = []
    for j, member in enumerate(members or []):
        r = _list_row(toks + (j,), member, row.sections)
        items.append({"index": j, "pointer": json_pointer(*r.toks),
                      **{k: _cell(ctx, r, k, "text", "analyze.compute_cable_map:cable.members[]." + k)
                         for k in ("a_port", "b_port")}})
    out["members"] = _listing(ctx, state, reason, toks, "analyze.compute_cable_map:cable.members", items,
                              sections=row.sections)
    ends = out["ends"]["value"] or {}
    out["a_nodes"], out["b_nodes"] = (_topology_join(ctx, ends.get(k)) for k in ("a", "b"))
    out["style"] = _topology_style([out["ends"], out["op_status"], out["a_nodes"], out["b_nodes"]],
                                    "link_" + (out["op_status"]["value"] or "unknown"))
    return out


#: The two link_centrality fields that name a structural link's unordered host pair.
_STRUCTURAL_HOSTS = ("a_host", "b_host")


def _structural_dup(ctx: _Ctx, raw: Any) -> Optional[_Withheld]:
    """The doubt on a link_centrality row whose unordered host pair another row also names (exact text, in either
    orientation). analyze.compute_link_centrality keys its links by that pair and writes one record per pair, so two
    rows naming one pair (an exact copy, the reversed orientation, or a contradicting record) cannot each be the
    producer's record, and no single one can be chosen (the _R_AMBIG precedent). Row-level, not list-level: the doubt
    is which record is the pair's, never which rows the list holds, so every such row keeps its index and pointer and
    withholds each of its cells as unverified, with a witness to every row naming the pair, while the list and its
    other pairs stay published. Distinct pairs that share a host (a device's several neighbours) are never doubted.
    ``None``: the row names no readable pair, or no other row names it."""
    if not (isinstance(raw, dict) and all(_is_text(raw.get(f)) for f in _STRUCTURAL_HOSTS)):
        return None
    same = ctx.pairs(("link_centrality",), _STRUCTURAL_HOSTS).get(frozenset(raw[f] for f in _STRUCTURAL_HOSTS), [])
    if len(same) < 2:
        return None
    return _UV, _R_PAIR_AMBIG.format(n=len(same)), [("witness", ("link_centrality", j)) for j in same]


def _topology_structural(ctx: _Ctx, i: int, raw: Any) -> Dict[str, Any]:
    """One structural-link row, shared by the fleet topology and the device page (one builder, one state)."""
    row = _list_row(("link_centrality", i), raw, ("link_centrality",))
    basis = "analyze.compute_link_centrality:link_centrality[]."
    dup = _structural_dup(ctx, raw)
    pre: Optional[_Pre] = (lambda _raw, _row: dup) if dup is not None else None
    out = {"index": i, "pointer": json_pointer(*row.toks),
           "ends": _cell(ctx, row, None, "structural_ends", basis + "endpoints", pre=pre)}
    for field, slot in (("betweenness", "nonnegative_number"), ("is_bridge", "flag"),
                        ("pairs_cut", "count"), ("rank", "positive_count")):
        out[field] = _cell(ctx, row, field, slot, basis + field, pre=pre, caveats=("topology_scanned_model",))
    ends = out["ends"]["value"] or {}
    # ends withheld by the pair doubt (not by a failed section): the joins are withheld with it, never "no hostname"
    held: Optional[_Withheld] = None
    if dup is not None and out["ends"]["state"] == dup[0] and out["ends"].get("reason") == dup[1]:
        held = dup
    out["a_nodes"], out["b_nodes"] = (_topology_join(ctx, ends.get(k), held) for k in _STRUCTURAL_HOSTS)
    toks = ("cable_map", "cables")
    state, reason, cables = _topology_source(ctx, toks)
    # the exact unordered host-pair join (ctx.pairs), held to the one key-join rule of _resolve: a cable row it
    # cannot read could cable this pair, so beside one the candidates are unverified, never a clean "no cable"
    pair = frozenset(ends.get(k) for k in _STRUCTURAL_HOSTS)
    hits = list(ctx.pairs(toks, ("a", "b")).get(pair, [])) if isinstance(cables, list) else []
    bad = ctx.unjoinable(toks, ("a", "b")) if isinstance(cables, list) else []
    if out["ends"]["state"] != _PUB:
        state, reason = out["ends"]["state"], out["ends"].get("reason")
        bad = []
    elif bad and state in (_PUB, _CBE):
        state, reason = _UV, _R_PAIR_UNJOINABLE.format(n=len(bad))
    else:
        bad = []
    out["host_pair_cable_refs"] = _listing(
        ctx, state, reason, toks, "ui_projection:exact unordered host-pair candidates (not per-cable centrality)",
        [{"index": j, "pointer": json_pointer(*toks, j)} for j in hits], sections=("cable_map",),
        extra=[("witness", toks + (j,)) for j in hits + bad] + (held[2] if held is not None else []),
        caveats=("topology_scanned_model",))
    out["style"] = _topology_style([out["ends"], out["is_bridge"], out["a_nodes"], out["b_nodes"]],
                                    "structural_bridge" if out["is_bridge"]["value"] else "structural_link")
    return out


#: analyze.compute_failure_impact's own opening for a switch whose blast radius it could not simulate. Owned, with
#: every row-level assessability rule, by the engine (impact_assessability); re-exported for the projection's
#: readers. Pinned to the real producer by tests/test_impact_assessability.py.
IMPACT_INDETERMINATE_PREFIX = impact_assessability.IMPACT_INDETERMINATE_PREFIX
#: The failure-impact cells that measure the simulated blast radius; host, off_scan_gw_vlans and detail are not.
_IMPACT_MEASURES = impact_assessability.IMPACT_MEASURES


def _run_config_captured(ctx: _Ctx, host: Any) -> bool:
    """Whether some interface of `host` carries ``run_config_observed: true``. build.py marks every interface its scoped
    interface running-config capture ('show running-config interface' or '| section ^interface') parsed, and takes the
    interface addresses (svi_ip, svi_ips) only from that capture. An absent marker reads as not captured: the snapshot
    drops a false one (html.sparsify_interfaces), and older snapshots carry none. One rule for the failure-impact hold
    and for the address index's coverage (:func:`_address_coverage`): this reads the failure-impact owner's scan
    (impact_assessability.run_config_captured, memoised per host by :attr:`_Ctx.impact`), never a second copy."""
    return _is_text(host) and ctx.impact.captured(host)[1]


def _impact_cable_source(ctx: _Ctx) -> impact_assessability.CableSource:
    """This context's reading of the stored cable map for the owner's neighbour bound
    (impact_assessability.neighbour_bound). The cable list takes the envelope state every topology list takes; one
    that cannot be read bounds each row with that state (unavailable and unverified stay, anything else is not
    collected), that reason, and a witness to the list (or its parent) plus the failure records of a failed cable
    map. A readable list carries this context's exact-text joins over it, and over the node list when that can be
    read (otherwise no far end joins a node, so every one fails closed)."""
    toks = ("cable_map", "cables")
    state, reason, cables = _topology_source(ctx, toks)
    if state not in (_PUB, _CBE):
        state = state if state in (AU, _UV) else _NC
        where = toks if _get(ctx.s, toks) is not _MISSING else ("cable_map",)
        return impact_assessability.unreadable_cables(
            state, reason or _R_NC, [("witness", where)] + ctx.failure_entries(("cable_map",), state == AU))
    ntoks = ("cable_map", "nodes")
    nstate, _nreason, nodes = _topology_source(ctx, ntoks)
    readable = nstate in (_PUB, _CBE) and isinstance(nodes, list)
    # F6: a node row the host join cannot read could be a second node for any far end, so the owner fails every far end
    # closed beside one (impact_assessability.neighbour_bound) and cites it; the join reads those rows here.
    return impact_assessability.readable_cables(
        cables, nodes if readable else None, by_end=ctx.index(toks, ("a", "b")),
        unjoinable=ctx.unjoinable(toks, ("a", "b")), node_index=ctx.index(ntoks, ("host",)) if readable else {},
        node_unjoinable=ctx.unjoinable(ntoks, ("host",)) if readable else [])


def _impact_pre(hold: Optional[impact_assessability.Hold], field: str,
                bounds: Sequence[impact_assessability.Bound]) -> _Pre:
    """One measure's pre-check, decided by the engine owner (impact_assessability.measure_withheld): the row's hold,
    else, on a bounded row, a severity below the worst band and a zero count. The worst band and a positive count
    stay published as lower bounds; a mistyped value falls through to the type check."""
    def pre(raw: Any, _row: _Row) -> Optional[Tuple[Any, ...]]:
        return impact_assessability.measure_withheld(hold, field, raw, bounds)
    return pre


def _impact_detail_pre(hold: Optional[impact_assessability.Hold],
                       bounds: Sequence[impact_assessability.Bound]) -> _Pre:
    """The detail's pre-check, decided by the engine owner (impact_assessability.detail_withheld): the producer's
    INDETERMINATE disclosure stays published, any other detail is held with the row's hold, and a bound that reaches
    the detail withholds one that names no simulated VLAN; a mistyped detail falls through to the type check."""
    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        return impact_assessability.detail_withheld(hold, raw, row.raw, bounds)
    return pre


def _ambiguous_pre(dup: _Withheld, inner: Optional[_Pre]) -> _Pre:
    """A duplicated row's pre-check, in the module's precedence (analysis unavailable, then unverified, then not
    collected; impact_assessability.bound_state, :func:`_topology_style`). The duplicate's unverified state wins over a
    hold or bound that withholds the cell as not collected, because that hold reads a row no one can say is the
    producer's; a bound that is analysis_unavailable (a failed cable map) wins over it. Either way the other reason
    and its witnesses are carried beside, so both negative observations survive (the _selection_rows precedent for a
    duplicate with a capture gap)."""
    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        early = inner(raw, row) if inner is not None else None
        if early is None:
            return dup
        more = list(early[2]) if len(early) > 2 else []
        if early[0] == AU:
            return AU, f"{early[1]}; {dup[1]}", more + dup[2]
        return dup[0], f"{dup[1]}; {early[1]}", dup[2] + more
    return pre


def _impact_witnessed(ctx: _Ctx, bound: impact_assessability.Bound) -> impact_assessability.Bound:
    """`bound` with every witness citing a record that resolves (W51; the W48 re-verification's P2, superseding W35's
    #626). A published lower bound is marked only by the witness refs its measures cite, and :meth:`_Ctx.refs` drops a
    pointer that does not resolve, so a bound whose witness is absent (a snapshot with no cable map at all, whose
    unreadable-list bound cites ``/cable_map``) would publish its High and positive counts as exact measurements while
    the engine owner (the MOP, the runbook) reads them as floors. An absent record is witnessed instead by the nearest
    record it is missing from, the longest prefix of its address that resolves (the cable map without its list, the
    snapshot root ``""`` without a cable map), never dropped; a present record, and every other role (a failure
    record), is cited as given."""
    def present(toks: Sequence[Any]) -> Tuple[Any, ...]:
        out = tuple(toks)
        while out and _get(ctx.s, out) is _MISSING:
            out = out[:-1]
        return out
    witnesses = [(role, present(toks) if role == "witness" else toks) for role, toks in bound.witnesses]
    return bound._replace(witnesses=witnesses)


def _topology_impact(ctx: _Ctx, i: int, raw: Any) -> Dict[str, Any]:
    """One failure-impact row, shared by the fleet topology and the device page (one builder, one state). Which of its
    values are measurements is the engine owner's row-level rule (impact_assessability: the duplicate doubt, the
    hold, then the off-scan, blind-link and uncollected-neighbour bounds); this builder only carries those facts
    into the envelopes, in the module's state precedence."""
    row = _list_row(("failure_impact", i), raw, ("failure_impact",))
    basis = "analyze.compute_failure_impact:failure_impact[]."
    out = {"index": i, "pointer": json_pointer(*row.toks)}
    dup, hold, bounds = ctx.impact.row(i, raw)
    # every measure of a bounded row cites what bounds it: the off-scan count, the blind-link count (or the row
    # itself when it predates that count), each uncollected neighbour's cable, or the cable list that cannot be read.
    # Each witness resolves (_impact_witnessed), so no bound is published unmarked.
    bounds = [_impact_witnessed(ctx, bound) for bound in bounds]
    cite = [w for bound in bounds for w in bound[4]]
    for field in ("host", "severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp",
                  "off_scan_gw_vlans", "detail"):
        slot = "text" if field in ("host", "detail") else "enum" if field == "severity" else "count"
        measure = field in _IMPACT_MEASURES
        pre = (_impact_pre(hold, field, bounds) if measure
               else _impact_detail_pre(hold, bounds) if field == "detail" else None)
        if dup is not None:
            pre = _ambiguous_pre(dup, pre)
        out[field] = _cell(ctx, row, field, slot, basis + field, vocab=IMPACT_SEVERITIES, pre=pre,
                           caveats=("impact_scanned_scope",), witness=cite if measure else ())
    # host withheld by the duplicate doubt (not by a failed section): its join is withheld with it
    held: Optional[_Withheld] = None
    if dup is not None and out["host"]["state"] == dup[0] and out["host"].get("reason") == dup[1]:
        held = dup
    out["node_refs"] = _topology_join(ctx, out["host"]["value"], held)
    severity = out["severity"]
    # A withheld severity is never styled as a neutral impact band: the withheld-state precedence picks the token.
    out["style"] = _topology_style([out["host"], severity, out["node_refs"]],
                                    "impact_" + severity["value"].lower() if severity["state"] == _PUB
                                    else "not_observed")
    return out


#: One positive address observation: ``(host, interface, origin, address, source tokens, family)``.
_Observation = Tuple[str, str, str, str, Tuple[Any, ...], int]
#: The inputs the address index reads; topology.source_addresses rolls its list state up over them.
_ADDRESS_SECTIONS: Tuple[str, ...] = ("interfaces", "routes")
_R_ADDRESS_MALFORMED = "unverified: malformed address source records were not usable"
_R_ADDRESS_BLIND = "not collected: this host is a recorded collection blind spot"


def _address_sources(ctx: _Ctx) -> Tuple[Tuple[_Observation, ...], Tuple[Tuple[Any, ...], ...],
                                         Mapping[str, Tuple[int, ...]]]:
    """The one address index, read through :attr:`_Ctx.addresses`: ``(observations, malformed, by_address)``. The
    positive interface/local/FHRP observations by FIB's ownership rules (fib._connected_index's exact owners: an
    interface address, a local host route, an FHRP host route naming itself; never a connected subnet, which every
    router on a shared segment contains), in the order topology.source_addresses publishes them; the source records
    that could not be read; and the observation indices of each address."""
    from cisco_toolkit import fib

    observations, malformed = [], []
    interfaces = ctx.s.get("interfaces")
    for section in ("interfaces", "routes"):
        if section in ctx.s and ctx.s[section] is not None and not isinstance(ctx.s[section], dict):
            malformed.append((section,))
    if isinstance(interfaces, dict):
        for host, ports in interfaces.items():
            if not _is_text(host) or not host or not isinstance(ports, dict):
                malformed.append(("interfaces",))
                continue
            for port, record in ports.items():
                if not _is_text(port) or not isinstance(record, dict):
                    malformed.append(("interfaces", host))
                    continue
                base = ("interfaces", host, port)
                values = [(record["svi_ip"], base + ("svi_ip",))] if "svi_ip" in record else []
                many = record.get("svi_ips")
                if isinstance(many, str):
                    values += [(v, base + ("svi_ips",)) for v in many.split(";")]
                elif isinstance(many, list):
                    values += [(v, base + ("svi_ips", j)) for j, v in enumerate(many)]
                elif many is not None:
                    malformed.append(base + ("svi_ips",))
                for raw, toks in values:
                    text, valid = fib._safe_token(raw)
                    if valid and not text:
                        continue
                    parsed = fib._ip(text.split()[0].split("/", 1)[0]) if valid and text else None
                    if parsed is None:
                        malformed.append(toks)
                    else:
                        observations.append((host, port, "interface_svi", str(parsed), toks, parsed.version))
    routes = ctx.s.get("routes")
    if isinstance(routes, dict):
        for host, rows in routes.items():
            if not _is_text(host) or not host or not isinstance(rows, list):
                malformed.append(("routes",))
                continue
            for j, row in enumerate(rows):
                if not isinstance(row, dict):
                    malformed.append(("routes", host, j))
                    continue
                source, source_valid = fib._safe_token(row.get("source"))
                if not source_valid or not source:
                    malformed.append(("routes", host, j) + (("source",) if "source" in row else ()))
                    continue
                if not fib._is_connected(source):
                    continue
                prefix, valid = fib._safe_token(row.get("prefix"))
                try:
                    network = ipaddress.ip_network(prefix, strict=False) if valid else None
                except ValueError:
                    network = None
                if network is None:
                    malformed.append(("routes", host, j))
                    continue
                source = source.lower().replace("*", "")
                local = source in {"l", "local"} or source.startswith("local")
                fhrp = any(k in source for k in ("hsrp", "vrrp", "glbp"))
                if network.prefixlen == network.max_prefixlen and (
                        local or (fhrp and fib._ip(row.get("next_hop")) == network.network_address)):
                    port = row.get("out_intf") if _is_text(row.get("out_intf")) else ""
                    observations.append((host, port, "local_route" if local else "fhrp_host_route",
                                         str(network.network_address), ("routes", host, j, "prefix"), network.version))
    ordered = tuple(sorted(observations, key=lambda x: x[:4] + (json_pointer(*x[4]),)))
    by_address: Dict[str, List[int]] = {}
    for k, observation in enumerate(ordered):
        by_address.setdefault(observation[3], []).append(k)
    return ordered, tuple(malformed), MappingProxyType({a: tuple(ks) for a, ks in by_address.items()})


def _address_hold(ctx: _Ctx, section: str, host: str) -> Tuple[Optional[Tuple[str, str]],
                                                               List[Tuple[str, Sequence[Any]]]]:
    """Why one address observation is withheld, with its witnesses; ``(None, [])`` when it is published. Match
    ssot.abstention_reason(device=...): a fully uncollected device is a blind spot even when the section's fleet
    analysis failed (the enclosing list still discloses that failure); otherwise a failed or faulted section; then
    (F6) a device scope that cannot say the host is not a blind spot leaves it unverified. The scope is read only
    through :meth:`_Ctx.device_scope`."""
    scope = ctx.device_scope(section, host)
    if scope is not None and scope[0] == _NC:
        return (_NC, _R_ADDRESS_BLIND), scope[2]
    hit = _secs_fail(ctx, (section,))
    if hit is None and scope is not None:
        return (scope[0], scope[1]), scope[2]
    return hit, []


def _address_observations(ctx: _Ctx) -> Dict[str, Any]:
    """Select positive interface/local/FHRP observations by FIB's ownership rules; no subnet host invention."""
    observations, malformed, _by_address = ctx.addresses
    items = []
    for i, (host, port, origin, address, toks, family) in enumerate(observations):
        section = toks[0]
        hit, witnesses = _address_hold(ctx, section, host)
        state, reason = hit or (_PUB, "")
        refs = ctx.refs([("subject", toks)] + ctx.failure_entries((section,), state == AU) + witnesses)
        def fact(value):
            return _envelope(state, value, None, [dict(r) for r in refs],
                             "fib._connected_index:positive address observation", reason,
                             caveats=("path_route_model_only",))
        items.append({"index": i, "pointer": json_pointer(*toks), "host": fact(host), "interface": fact(port),
                      "address": fact(address), "family": fact(family), "origin": fact(origin),
                      "node_refs": _topology_join(ctx, host)})
        if not port and state == _PUB:
            items[-1]["interface"] = _envelope(_NC, None, json_pointer(*toks), refs,
                                                "fib._connected_index:address interface", "not collected: no interface")
    state, reason = (_UV, _R_ADDRESS_MALFORMED) if malformed else (_PUB, None)
    return _listing(ctx, state, reason, None, "fib._connected_index:positive address observations", items,
                    sections=_ADDRESS_SECTIONS, rollup=_ADDRESS_SECTIONS,
                    extra=[("witness", t) for t in malformed], caveats=("path_route_model_only",))


#: The sections whose host keys name a collected device to the address index's coverage check: the inventory (devices),
#: and every per-host capture that only a reached device can carry.
_ADDRESS_ROSTER: Tuple[str, ...] = ("devices", "interfaces", "routes", "routing_neighbors")
#: The record that completes that roster: analyze.compute_collection_completeness lists every inventory device that was
#: not fully collected (its 'devices' rows), including one the collection never reached, which no roster section names.
_ADDRESS_ROSTER_RECORD = "collection_completeness"
#: One coverage gap of the address index: the witness ref entries that show it (none may resolve: an absent record).
_CoverageGap = Tuple[Tuple[str, Sequence[Any]], ...]


def _address_coverage(ctx: _Ctx) -> Tuple[bool, Tuple[_CoverageGap, ...]]:
    """Whether the address index can hold every collected device's interface addresses, read through
    :attr:`_Ctx.address_coverage`: ``(complete, gaps)``. The roster is every device a host key of
    :data:`_ADDRESS_ROSTER` names, completed by the :data:`_ADDRESS_ROSTER_RECORD` rows. Each roster device is a gap
    when collection_completeness calls it not collected, or when no interface of it carries run_config_observed
    (:func:`_run_config_captured`), the only capture its interface addresses come from. Every record row that does not
    name a roster device (by the owner's name rule) is a gap, whatever its status: a device outside the roster, or a
    row that names none (not an object, or a host that is not text). The roster itself is unknown, so completeness is
    never claimed, when the devices map cannot be read, or when the record cannot be trusted, read through its one
    coverage verdict (:meth:`_Ctx.cc_coverage`, W51): absent, failed (its failure records ride in the gap), faulted,
    a list or section of the wrong type, or a summary that cannot be read or does not reconcile with its rows or with
    the roster. The record's own row rule here (a row naming no roster device) stands in for its unread-rows gap."""
    ifaces = ctx.s.get("interfaces")
    gaps: List[_CoverageGap] = []
    roster: Dict[str, str] = {}               # device -> the first roster section naming it (its witness otherwise)
    for section in _ADDRESS_ROSTER:
        keyed = ctx.s.get(section)
        if isinstance(keyed, dict):
            for name in keyed:
                if _is_text(name):
                    roster.setdefault(name, section)
                elif section == "devices":
                    gaps.append((("witness", ("devices",)),))
        elif section == "devices":
            gaps.append((("witness", ("devices",)),))
    for name in sorted(roster):
        # the owner's blind-spot answer is read only through the device scope's door (F6). A scope in doubt adds no
        # gap of its own here: a record row naming no roster device, or a record that cannot be read, is a gap below,
        # and for a device the record does name, its own interface capture (the only source of its addresses) is
        # checked directly
        scope = ctx.device_scope("interfaces", name)
        if scope is not None and scope[0] == _NC:
            gaps.append(tuple(scope[2]))
        elif not _run_config_captured(ctx, name):
            gaps.append((("witness", ("interfaces", name) if isinstance(ifaces, dict) and name in ifaces
                          else (roster[name], name)),))
    for cc_gap in ctx.cc_coverage().gaps:
        if cc_gap.kind != _CC_UNREAD_ROWS:             # the row rule below reads every row that names no roster device
            gaps.append(tuple(cc_gap.entries()))
    rows = _get(ctx.s, (_ADDRESS_ROSTER_RECORD, "devices"))
    if isinstance(rows, list):
        named = {_norm(name) for name in roster}
        for i, row in enumerate(rows):
            listed = row.get("host") if isinstance(row, dict) else None
            if not (_is_text(listed) and _norm(listed) in named):
                gaps.append((("witness", (_ADDRESS_ROSTER_RECORD, "devices", i)),))
    return not gaps, tuple(gaps)


#: G17: the owner chain a peer_host fact cites. The address index is fib._connected_index's exact ownership (published
#: as topology.source_addresses); more than one owning device is ambiguous by fib._hosts_owning_ip's rule.
_B_PEER = ("fib._hosts_owning_ip(exact) over topology.source_addresses (fib._connected_index): the collected device "
           "carrying build.build_routing_neighbors:routing_neighbors{}{}[].")
_PEER_CAVEAT = "routing_peer_resolution_scope"
#: The states an address observation can be withheld with (:func:`_address_hold`), in the module's precedence.
_HOLD_ORDER: Tuple[str, ...] = (AU, _UV, _NC)
_R_PEER_NO_FIELD = ("not collected: no neighbour-address field is registered for the routing protocol '{proto}' "
                    "(NEIGHBOR_ADDRESS_FIELDS), so no address of this row is resolved")
_R_PEER_EMPTY = "not collected: the neighbour row's {field} is empty, so there is no address to resolve"
_R_PEER_NOT_IP = "unverified: the neighbour row's {field} is not an IP address, so it names no owner"
_R_PEER_AMBIG = ("unverified: the address index (topology.source_addresses) places this address on {n} collected "
                 "devices{among}, and more than one owner is ambiguous (fib._hosts_owning_ip), so no single peer can "
                 "be chosen")
_R_PEER_AMONG = " (this device among them)"
_R_PEER_SELF = ("unverified: the address index (topology.source_addresses) places this address only on this device "
                "itself, and a routing neighbour is another router, so the address cannot name the peer")
_R_PEER_MALFORMED = ("unverified: {n} address source record(s) cannot be read (topology.source_addresses is "
                     "unverified), and any of them could carry this address")
_R_PEER_HELD = ("{why} (the one device the address index places this address on), so the address index "
                "(topology.source_addresses) withholds that observation, and this peer with it")
_R_PEER_FAMILY = ("not collected: the address index holds interface addresses only from the running-config 'ip "
                  "address' and 'ipv4 address' lines (parse.parse_run_config_interfaces), which are IPv4, so whether a "
                  "collected device carries this IPv6 address was never observed")
_R_PEER_FAMILY_OWNED = ("not collected: an IPv6 owner is observed (each observation is a witness), but the address "
                        "index's IPv6 coverage is incomplete: the interface addresses it takes from the running-config "
                        "are the IPv4 'ip address' and 'ipv4 address' lines (parse.parse_run_config_interfaces), so "
                        "another device carrying this IPv6 address was never ruled out and a sole owner cannot be "
                        "claimed")
#: A sole owner, like an absence, is claimed only over a complete index: a device the index cannot hold could be a
#: second owner, and more than one owner is ambiguous (fib._hosts_owning_ip).
_R_PEER_INCOMPLETE = ("not collected: the address index (topology.source_addresses) may be incomplete, because {why}, "
                      "so {tail}")
_R_PEER_WHY_INPUTS = "inputs it is built from were not collected ({sections})"
_R_PEER_WHY_GAPS = ("it has {n} coverage gap(s): a collected device whose interface addresses it does not hold (a "
                    "collection blind spot, or no interface carries run_config_observed: true, so no scoped interface "
                    "running-config was parsed), a collection_completeness row that names no device of the roster, or "
                    "a device roster (the devices map, or the collection_completeness record that completes it) that "
                    "is absent, failed or unreadable{cited}")
_R_PEER_CITED = "; the witnesses cite the first {k} of them"
_R_PEER_CITED_FAILURES = ", and every failure record behind the rest"
_R_PEER_TAIL_ABSENT = "an address it does not hold is not a clean result"
_R_PEER_TAIL_OWNER = ("the one device it places this address on cannot be named the only owner: a second owner was "
                      "never ruled out, and more than one owner is ambiguous (fib._hosts_owning_ip)")
#: At most this many coverage gaps are cited as witnesses on one peer_host fact. The reason states the total, so a fleet
#: whose interface addresses were mostly not captured does not repeat its roster on every neighbour row.
_PEER_GAPS_CITED = 8
_R_PEER_NOT_RESOLVED = ("collected but empty: not resolved. No record in the address index (topology.source_addresses) "
                        "states this address: no collected device's configured IPv4 interface address (the 'ip "
                        "address' and 'ipv4 address' lines of its captured interface running-config) and no in-scope "
                        "local or FHRP host route. An address neither source states is not observed, such as a DHCP or "
                        "negotiated interface address whose local route was not captured in scope, or a firewall's "
                        "failover standby address, so this does not prove that the neighbour is not a collected device")


def _peer_host(ctx: _Ctx, host: Any, proto: str, toks: Tuple[Any, ...],
               cells: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
    """G17: the collected device a routing neighbour's address belongs to, or 'not resolved', read from the one address
    index (:attr:`_Ctx.addresses`, published as topology.source_addresses): never a second index, never a subnet guess.
    The address is the row's :data:`NEIGHBOR_ADDRESS_FIELDS` cell, whose withheld state withholds the resolution. Then,
    first match wins, in the module's precedence (analysis unavailable, then unverified, then not collected): a failed
    or faulted index input -> an address that is not an IP -> more than one owning device, or only this device ->
    an unreadable source record that could also carry it -> an owning observation the index withholds -> an IPv6
    address -> an index that may be incomplete (an uncollected input, or a coverage gap of :func:`_address_coverage`,
    the first :data:`_PEER_GAPS_CITED` cited, and every failure record behind any of them): not collected, for a sole observed owner as for an absence, since an
    unheld device could be a second owner -> over a complete index, one owner is published, citing every observation of
    it, and no owner is 'not resolved', collected but empty."""
    from cisco_toolkit import fib

    field = NEIGHBOR_ADDRESS_FIELDS.get(proto)
    if field is None:
        return _envelope(_NC, None, None, ctx.refs([("subject", toks)]), _B_PEER.rstrip("."),
                         _R_PEER_NO_FIELD.format(proto=proto))
    basis = _B_PEER + field
    cell = cells[field]
    if cell["state"] != _PUB:
        refs = [dict(ref) for ref in cell["refs"]]
        if cell["state"] == _CBE:
            return _envelope(_NC, None, None, refs, basis, _R_PEER_EMPTY.format(field=field))
        return _envelope(cell["state"], None, None, refs, basis, cell["reason"])
    base = [("subject", toks + (field,))] + [("basis", (s,)) for s in _ADDRESS_SECTIONS]
    failed = _secs_fail(ctx, _ADDRESS_SECTIONS)
    if failed is not None:
        return _envelope(failed[0], None, None,
                         ctx.refs(base + ctx.failure_entries(_ADDRESS_SECTIONS, failed[0] == AU)), basis, failed[1])
    ip = fib._ip(cell["value"])
    if ip is None:
        return _envelope(_UV, None, None, ctx.refs(base), basis, _R_PEER_NOT_IP.format(field=field))
    observations, malformed, by_address = ctx.addresses
    hits = [observations[k] for k in by_address.get(str(ip), ())]
    owners = sorted({hit[0] for hit in hits})
    wit = [("witness", hit[4]) for hit in hits]
    if len(owners) > 1:
        return _envelope(_UV, None, None, ctx.refs(base + wit), basis,
                         _R_PEER_AMBIG.format(n=len(owners), among=_R_PEER_AMONG if host in owners else ""))
    if owners == [host]:
        return _envelope(_UV, None, None, ctx.refs(base + wit), basis, _R_PEER_SELF)
    owner = owners[0] if owners else None
    # an unreadable record could carry the address: for an owner, any record that is not the owner's own
    bad = [t for t in malformed if owner is None or len(t) < 2 or t[1] != owner]
    if bad:
        return _envelope(_UV, None, None, ctx.refs(base + wit + [("witness", t) for t in bad]), basis,
                         _R_PEER_MALFORMED.format(n=len(bad)))
    held = [hold for hold in (_address_hold(ctx, hit[4][0], hit[0]) for hit in hits) if hold[0] is not None]
    if held:
        (worst, why), _its_witnesses = min(held, key=lambda hold: _HOLD_ORDER.index(hold[0][0]))
        return _envelope(worst, None, None, ctx.refs(base + wit + [w for hold in held for w in hold[1]]), basis,
                         _R_PEER_HELD.format(why=why))
    if ip.version != 4:
        return _envelope(_NC, None, None, ctx.refs(base + wit), basis, _R_PEER_FAMILY_OWNED if hits else _R_PEER_FAMILY)
    tail = _R_PEER_TAIL_ABSENT if owner is None else _R_PEER_TAIL_OWNER
    uncollected = [s for s in _ADDRESS_SECTIONS if ctx.abst(s) == _NC]
    if uncollected:
        return _envelope(_NC, None, None, ctx.refs(base + wit), basis, _R_PEER_INCOMPLETE.format(
            why=_R_PEER_WHY_INPUTS.format(sections=", ".join(uncollected)), tail=tail))
    complete, gaps = ctx.address_coverage
    if not complete:
        cited = gaps[:_PEER_GAPS_CITED]
        # a failure record is never dropped by the cap (W51): the failed phase is what explains the gap
        failures = [entry for gap in gaps[_PEER_GAPS_CITED:] for entry in gap if entry[0] == "failure_record"]
        why = _R_PEER_WHY_GAPS.format(
            n=len(gaps), cited=(_R_PEER_CITED.format(k=len(cited)) + (_R_PEER_CITED_FAILURES if failures else ""))
            if len(cited) < len(gaps) else "")
        return _envelope(_NC, None, None,
                         ctx.refs(base + wit + [entry for gap in cited for entry in gap] + failures), basis,
                         _R_PEER_INCOMPLETE.format(why=why, tail=tail))
    if owner is not None:
        return _envelope(_PUB, owner, None, ctx.refs(base + wit), basis, "", caveats=(_PEER_CAVEAT,))
    return _envelope(_CBE, None, None, ctx.refs(base), basis, _R_PEER_NOT_RESOLVED, caveats=(_PEER_CAVEAT,))


def _topology_source(ctx: _Ctx, toks: Tuple[str, ...]) -> Tuple[str, Optional[str], Any]:
    state, reason, raw = _list_state(ctx, toks, (toks[0],))
    if len(toks) > 1 and state != AU:
        parent = ctx.s.get(toks[0])
        if parent is not None and not isinstance(parent, dict):
            return _UV, "unverified: the stored topology parent is not an object", None
    return state, reason, raw


def _topology(ctx: _Ctx) -> Dict[str, Any]:
    out = {}
    # The structural and impact rows are computed over every scanned device's evidence: a blind spot qualifies
    # them (fleet_lists_exclude_blind_devices). Nodes and cables are discovery observations whose uncollected
    # peers stay visible as rows (topology_scanned_model).
    fleet = _fleet_qualify(ctx)
    for field, toks, producer, qualify in (
            ("nodes", ("cable_map", "nodes"), _topology_node, ()),
            ("cables", ("cable_map", "cables"), _topology_cable, ()),
            ("structural_links", ("link_centrality",), _topology_structural, fleet),
            ("failure_impact", ("failure_impact",), _topology_impact, fleet)):
        state, reason, rows = _topology_source(ctx, toks)
        out[field] = _listing(ctx, state, reason, toks, "ui_projection:stored " + ".".join(toks),
                              [producer(ctx, i, row) for i, row in enumerate(rows or [])], sections=(toks[0],),
                              caveats=("topology_scanned_model",), qualify=qualify)
    summary = _resolve(ctx, ("cable_map", "summary"), ("cable_map",))
    if summary.state == _NC and ctx.s.get("cable_map") is not None and not isinstance(ctx.s["cable_map"], dict):
        summary.state, summary.reason = _UV, "unverified: the stored topology parent is not an object"
    out["summary"] = {}
    for field in ("nodes", "cables"):
        def consistent(_ctx, value, _row, name=field):
            raw = _get(ctx.s, ("cable_map", name))
            witness = [("witness", ("cable_map", name))]
            if raw is _MISSING or raw is None:
                return _NC, "not collected: summary has no observed source list", witness
            if not isinstance(raw, list):
                return _UV, "unverified: summary source is present but is not a list", witness
            if value != len(raw):
                return _UV, "unverified: stored summary contradicts the stored source list", witness
            return None
        out["summary"][field] = _cell(ctx, summary, "n_" + field, "count", "analyze.compute_cable_map:summary.n_" + field,
                                      gate=consistent, caveats=("topology_scanned_model",))
    out["source_addresses"], out["legend"] = _address_observations(ctx), _topology_legend()
    return out


def project_topology(snap: Any) -> Dict[str, Any]:
    """Stored topology, exact evidence joins and engine-owned presentation; no legacy recomputation."""
    return _topology(_Ctx(snap))


def fleet_blind_spot_rows(snap: Any) -> List[int]:
    """The ``collection_completeness.devices`` rows the fleet qualifier (``fleet_lists_exclude_blind_devices``) reads
    as a partial or not-collected device, by index (:meth:`_Ctx.blind_rows`). Every other witness the qualifier cites
    is a row it cannot read as one, or a list or section it cannot read at all, so a consumer telling the two apart
    reads this one classifier and never re-reads the stored rows."""
    return _Ctx(snap).blind_rows()


def _fib_value(raw: Any) -> Optional[Dict[str, Any]]:
    """Type-check the disclosed owner result without interpreting its verdict or deleting evidence."""
    def text_record(value, fields, optional=()):
        return (isinstance(value, dict) and set(fields) <= set(value) <= set(fields) | set(optional)
                and all(_is_text(value[k]) for k in fields))

    def hop(value):
        return (text_record(value, ("host", "match", "next_hop", "out_intf", "source"), ("invalid_route_fields",))
                and ("invalid_route_fields" not in value or (
                    isinstance(value["invalid_route_fields"], list) and bool(value["invalid_route_fields"])
                    and all(v in FIB_ROUTE_FIELDS
                            for v in value["invalid_route_fields"] if isinstance(v, str))
                    and all(isinstance(v, str) for v in value["invalid_route_fields"]))))

    def mtu(value, required=False):
        fields = ("host", "out_intf", "mtu", "required") if required else ("host", "out_intf", "mtu")
        return (isinstance(value, dict) and set(value) == set(fields)
                and all(_is_text(value[k]) for k in ("host", "out_intf"))
                and all(_count(value[k])[0] for k in fields[2:]))

    fields = ("src", "dst", "hops", "status", "computed", "reached", "drop_evidence", "ecmp_dropping_legs",
              "ambiguous_candidate_sets", "mtu_min", "mtu_bottleneck_hop", "mtu_unobserved_hops",
              "jumbo_blackhole", "mtu_verdict")
    if not (isinstance(raw, dict) and set(raw) == set(fields)
            and all(_is_text(raw[k]) for k in ("src", "dst", "status", "drop_evidence", "mtu_verdict"))
            and all(isinstance(raw[k], bool) for k in ("computed", "reached"))
            and all(isinstance(raw[k], list) for k in ("hops", "ecmp_dropping_legs", "ambiguous_candidate_sets",
                                                       "mtu_unobserved_hops", "jumbo_blackhole"))
            and all(hop(h) for h in raw["hops"])
            and (raw["mtu_min"] is None or _count(raw["mtu_min"])[0])
            and (raw["mtu_bottleneck_hop"] is None or mtu(raw["mtu_bottleneck_hop"]))
            and all(mtu(m, True) for m in raw["jumbo_blackhole"])):
        return None
    for leg in raw["ecmp_dropping_legs"]:
        texts = ("host", "match", "next_hop", "out_intf", "leg_status", "drop_evidence")
        if not (text_record(leg, texts, ("resolved_hops",)) and "resolved_hops" in leg
                and isinstance(leg["resolved_hops"], list) and all(hop(h) for h in leg["resolved_hops"])):
            return None
    for group in raw["ambiguous_candidate_sets"]:
        if not (isinstance(group, dict) and set(group) == {"kind", "candidate_hosts"}
                and _is_text(group["kind"]) and _text_list(group["candidate_hosts"])[0]):
            return None
    for gap in raw["mtu_unobserved_hops"]:
        if not (text_record(gap, ("host", "out_intf"), ("reason",))
                and ("reason" not in gap or gap["reason"] in FIB_MTU_GAP_REASONS)):
            return None
    return _copy_schema(raw)


def _path_hop_evidence(ctx: _Ctx, i: int, hop: Dict[str, Any]) -> Dict[str, Any]:
    from cisco_toolkit import fib

    host, port = hop["host"], hop["out_intf"]
    route_toks = ("routes", host)
    row = _resolve(ctx, ("routes",), ("routes",), key=host, want=list, host=host)
    raw = row.raw if isinstance(row.raw, list) else []
    hits = []
    for j, route in enumerate(raw):
        if not isinstance(route, dict):
            continue
        prefix, valid = fib._safe_token(route.get("prefix"))
        try:
            match = str(ipaddress.ip_network(prefix, strict=False)) if valid else None
        except ValueError:
            match = None
        if match == hop["match"] and ("invalid_route_fields" in hop or all(
                fib._safe_token(route.get(k))[0] == hop[k] and fib._safe_token(route.get(k))[1]
                for k in ("next_hop", "out_intf", "source"))):
            hits.append(j)
    state, reason = row.state, row.reason
    if state is None:
        if len(hits) == 1 and "invalid_route_fields" not in hop:
            state = _PUB
        elif hits:
            state, reason = _UV, "unverified: route evidence is ambiguous or the owner disclosed malformed fields"
        else:
            state, reason = _NC, "not collected: no exact stored route row matches this computed hop"
    routes = _listing(ctx, state, reason, route_toks, "fib.trace_fib_path:exact route evidence join",
                      [{"index": j, "pointer": json_pointer(*route_toks, j)} for j in hits], sections=("routes",),
                      extra=list(row.extra) + [("witness", route_toks + (j,)) for j in hits],
                      caveats=("path_route_model_only",))
    iface_toks = ("interfaces", host, port)
    iface = _resolve(ctx, ("interfaces",), ("interfaces",), key=host, want=dict, host=host)
    state, reason = iface.state, iface.reason
    refs = []
    if state is None:
        value = _get(ctx.s, iface_toks)
        if isinstance(value, dict) and port:
            state = _PUB
            refs = [{"pointer": json_pointer(*iface_toks), "role": "witness"}]
        elif value is not _MISSING and not isinstance(value, dict):
            state, reason = _UV, "unverified: the hop interface record is malformed"
        else:
            state, reason = _NC, "not collected: no exact interface record for this computed hop"
    interfaces = _listing(ctx, state, reason, None, "fib.trace_fib_path:exact egress-interface join", refs,
                          sections=("interfaces",), extra=list(iface.extra) + [("witness", iface_toks)],
                          caveats=("path_route_model_only",))
    return {"hop_index": i, "route_rows": routes, "interfaces": interfaces, "node_rows": _topology_join(ctx, host)}


def project_path(snap: Any, src_ip: Any, dst_ip: Any) -> Dict[str, Any]:
    """One offline, disclosed FIB query; separate from the immutable snapshot's static projection."""
    from cisco_toolkit import fib

    ctx = _Ctx(snap)
    engine = _engine(ctx)              # G41: the source identity is read before any owner below touches the snapshot
    sections = ("routes", "interfaces", "routing_neighbors", "l3_forwarding")
    hit = _secs_fail(ctx, sections)
    routes = ctx.s.get("routes", _MISSING)
    if not hit and (routes is _MISSING or routes is None):
        hit = (_NC, "not collected: this snapshot has no routes for a path query")
    elif not hit and not isinstance(routes, dict):
        hit = (_UV, "unverified: the routes section is not a host map")
    elif not hit and not routes:
        hit = (_CBE, "collected but empty: no route hosts were recorded")
    value = None
    if not hit:
        try:
            value = _fib_value(fib.trace_fib_path(ctx.s, src_ip, dst_ip, max_hops=32, required_mtu=None, disclose=True))
            if value is None:
                hit = (_UV, "unverified: the FIB owner returned an unsupported result shape")
        except _OWNER_FAULTS as exc:
            hit = (_UV, _fault_text("fib.trace_fib_path", exc))
    state, reason = hit or (_PUB, "")
    refs = ctx.refs([("basis", (s,)) for s in sections] + ctx.failure_entries(sections, state == AU))
    result = _envelope(state, value, None, refs, "fib.trace_fib_path(disclose=True)", reason,
                       caveats=("path_route_model_only",))
    evidence = [_path_hop_evidence(ctx, i, hop) for i, hop in enumerate(value["hops"])] if value else []
    if state != _PUB:
        token = "path_withheld"
    elif value["reached"]:
        token = "path_partial_drop" if value["ecmp_dropping_legs"] else "path_reached"
    elif value["drop_evidence"] == "observed_discard":
        token = "path_observed_discard"
    elif value["drop_evidence"] == "no_route_observed":
        token = "path_no_route_observed"
    else:
        token = "path_lower_bound"
    style = _topology_style([result], token)
    style["caveats"] = ["path_route_model_only"]
    path = {"query": {"src_ip": src_ip if _is_text(src_ip) else "", "dst_ip": dst_ip if _is_text(dst_ip) else "",
                       "max_hops": 32, "required_mtu": None, "disclose": True},
            "result": result, "hop_evidence": _listing(ctx, state, reason, None, "fib.trace_fib_path:hops evidence",
                                                       evidence, sections=sections, caveats=("path_route_model_only",)),
            "style": style, "legend": _topology_legend()}
    return {"schema": SCHEMA, "engine": engine, "path": path, "vocab": _vocab()}


# ---------------------------------------------------------------------------------------------------
# vocab -- the engine-owned display rank and severity class of every closed vocabulary (G43)
# ---------------------------------------------------------------------------------------------------
VOCAB_SCHEMA = "ui_projection_vocab/1"
#: The severity classes a glyph may draw. ``undetermined`` is the coverage-honesty class: the owner determines
#: no level (absence, insufficiency, unknown, unassessed, informational), so a glyph draws none -- never ``pass``.
VOCAB_CLASSES: Tuple[str, ...] = ("pass", "watch", "risk", "critical", "undetermined")
_C_PASS, _C_WATCH, _C_RISK, _C_CRIT, _C_UND = VOCAB_CLASSES
_PRESENTATION_OWNER = "cisco_toolkit.ui_projection"


def _classed(tokens: Tuple[str, ...], classes: Tuple[str, ...]) -> Dict[str, str]:
    """Class per token, ``classes`` aligned one-to-one with the vocabulary's own owner tuple ``tokens``.

    A vocabulary that shares spellings with the protocol-assessability receipt's states is never re-typed
    here: its tokens come only from its owner tuple, so this section dependency names no receipt state.
    ``strict`` makes a resized owner tuple fail at import instead of shifting a class onto a neighbouring
    token."""
    return dict(zip(tokens, classes, strict=True))


def _ranked_by(tokens: Tuple[str, ...], ranks: Tuple[int, ...]) -> Tuple[Tuple[str, ...], ...]:
    """The display order of such a vocabulary from a rank aligned one-to-one with its owner tuple: one group
    per rank, lowest first, tokens of one rank in the owner tuple's order."""
    rank_of = dict(zip(tokens, ranks, strict=True))
    return tuple(tuple(token for token in tokens if rank_of[token] == rank) for rank in sorted(set(ranks)))


#: Ranked vocabularies: (name, tokens in schema order, owner of the order, basis, display order, class per
#: token). A display-order element is a token or a tuple of tokens the owner does not order apart (they share
#: a rank). The order of an engine-ranked vocabulary IS its local constant, which tests/test_ui_projection*.py
#: hold equal to the owner's rank table; ``tests/test_ui_projection_vocab.py`` holds every rank and class.
#: A vocabulary whose tokens share spellings with the receipt's states (collection status, security grade,
#: coverage state, unknown-evidence source state) states its order and classes through :func:`_ranked_by` and
#: :func:`_classed`, aligned with its owner tuple; the comment beside each names the tokens in that order.
_VOCAB_RANKED: Tuple[Tuple[str, Tuple[str, ...], str, str, Tuple[Any, ...], Mapping[str, str]], ...] = (
    ("health_band", HEALTH_BANDS, "ssot._HEALTH_BAND_ORDER",
     "rank: the ssot worst-band order (the most severe band present wins, as analyze.compute_executive_brief "
     "folds it). class: Critical is the owner's top band; Poor is the band the brief grades High, a gating "
     "severity; Fair needs attention; Good and Excellent are measured acceptable scores.",
     HEALTH_BANDS, {"Critical": _C_CRIT, "Poor": _C_RISK, "Fair": _C_WATCH, "Good": _C_PASS, "Excellent": _C_PASS}),
    ("health_band_partition", HEALTH_BANDS + (HEALTH_BAND_NOT_SCORED,), "analyze._APP_BAND_RANK",
     "rank: the owner's band rank over the health partition, the unscored band last. class: as health_band; "
     "the unscored band is a collection gap the owner never counts as a band, so it determines no level.",
     HEALTH_BANDS + (HEALTH_BAND_NOT_SCORED,),
     {"Critical": _C_CRIT, "Poor": _C_RISK, "Fair": _C_WATCH, "Good": _C_PASS, "Excellent": _C_PASS,
      HEALTH_BAND_NOT_SCORED: _C_UND}),
    ("lifecycle_band", LIFECYCLE_BAND_ORDER, "analyze._LIFECYCLE_BAND_RANK",
     "rank: the owner's band rank, most severe first, Unknown last. class: Past-LDoS is past the last day of "
     "support; Near-LDoS is inside the owner's warning window; Past-EoS is sold-out hardware still supported; "
     "Active is a measured current lifecycle; Unknown is the owner's not-determined band.",
     LIFECYCLE_BAND_ORDER, {"Past-LDoS": _C_CRIT, "Near-LDoS": _C_RISK, "Past-EoS": _C_WATCH, "Active": _C_PASS,
                            "Unknown": _C_UND}),
    ("risk_band", DOSSIER_BANDS, "analyze._DOSSIER_BAND_RANK",
     "rank: the owner's band rank, most severe first, Unassessed last. class: the dossier's risk-index bands "
     "from Severe down to a measured Low; Unassessed is the owner's no-evidence band, never low risk.",
     DOSSIER_BANDS, {"Severe": _C_CRIT, "Elevated": _C_RISK, "Guarded": _C_WATCH, "Low": _C_PASS,
                     "Unassessed": _C_UND}),
    ("vlan_readiness", VLAN_READINESS, "analyze._VLAN_CUTOVER_READY_RANK",
     "rank: the owner's worst-first pull-through rank. class: NOT READY gates the cutover; CAUTION needs "
     "attention; READY is the owner's measured verdict.",
     VLAN_READINESS, {"NOT READY": _C_RISK, "CAUTION": _C_WATCH, "READY": _C_PASS}),
    ("readiness_check_status", READINESS_CHECK_STATUSES, "analyze.compute_migration_readiness (status_rank)",
     "rank: the owner folds a group's checks with pass and info at the same rank below warn below fail; shown "
     "worst first. class: fail gates; warn needs attention; pass is a measured check; info is an informational "
     "or not-observable check that determines no level.",
     ("fail", "warn", ("pass", "info")), {"fail": _C_RISK, "warn": _C_WATCH, "pass": _C_PASS, "info": _C_UND}),
    ("endpoint_confidence", ENDPOINT_CONFIDENCES, "analyze._EP_CONF",
     "rank: the owner's confidence score, most confident first, Unknown last. class: the class grades the "
     "inference's confidence, not the endpoint: a medium-confidence class needs review before a move-group "
     "assignment; Unknown is the owner's undetermined confidence.",
     ENDPOINT_CONFIDENCES, {"Inferred-high": _C_PASS, "Inferred-medium": _C_WATCH, "Unknown": _C_UND}),
    ("collection_status", CC_STATUSES, "analyze.compute_collection_completeness (order)",
     "rank: the owner's blind-spot order, least evidence first (the owner lists only blind spots, never "
     "complete). class: a not-collected device determines nothing; a partial device has observed evidence "
     "that may be incomplete.",
     CC_STATUSES, _classed(CC_STATUSES, (_C_UND, _C_WATCH))),                 # not collected, partial
    ("link_op_status", OP_STATUSES, _PRESENTATION_OWNER,
     "rank: no engine owner orders analyze.compute_cable_map's op_status; this projection shows down first, "
     "unknown last, as its topology legend does (link_down danger, link_up info, link_unknown muted). class: "
     "a reported down link is a risk, a reported up link is acceptable, unknown is the owner's coverage-honest "
     "absence and determines no level.",
     ("down", "up", "unknown"), {"down": _C_RISK, "up": _C_PASS, "unknown": _C_UND}),
    ("severity", SEVERITIES, "analyze._APP_SEV_RANK",
     "rank: the owner's severity rank (analyze._PUNCH_RANK descending, Info at its implicit rank below Low). "
     "class: Critical is the top tier; High is the other gating tier of the brief's top_gating rule; Medium "
     "and Low are determined findings that do not gate; Info rows record a coverage gap or information, never "
     "a finding level.",
     SEVERITIES, {"Critical": _C_CRIT, "High": _C_RISK, "Medium": _C_WATCH, "Low": _C_WATCH, "Info": _C_UND}),
    ("impact_severity", IMPACT_SEVERITIES, "analyze.compute_failure_impact (sev_rank)",
     "rank: the owner's sev_rank, worst first. class: High is a hard partition on removal (an outage class, "
     "drawn danger and strong by the topology legend); Medium survives only through a backup path (the "
     "legend's warning); Low is FHRP-covered on every impacted VLAN within the scan; Info is the owner's "
     "INDETERMINATE or no-impact-within-the-scan result, not a clean bill, so it determines no level.",
     IMPACT_SEVERITIES, {"High": _C_CRIT, "Medium": _C_WATCH, "Low": _C_PASS, "Info": _C_UND}),
    ("exposure_state", EXPOSURE_STATES, _PRESENTATION_OWNER,
     "rank: analyze.compute_device_dossiers names its ax() states without an order; this projection shows "
     "risk first, na last. class: the states carry their own level; na is the owner's not-assessable axis "
     "(input absent, malformed or unavailable) and determines no level.",
     EXPOSURE_STATES, {"risk": _C_RISK, "watch": _C_WATCH, "ok": _C_PASS, "na": _C_UND}),
    ("security_grade", SEC_GRADES, "parse.parse_security (grade precedence)",
     "rank: the owner's grade precedence: weak when a high-severity check fails, partial when any check "
     "fails, hardened otherwise. class: weak is a failed high-severity hardening check; partial needs "
     "attention; hardened is the owner's verdict over the checks it evaluated.",
     SEC_GRADES, _classed(SEC_GRADES, (_C_RISK, _C_WATCH, _C_PASS))),        # weak, partial, hardened
    ("security_check_status", SEC_STATUSES, _PRESENTATION_OWNER,
     "rank: parse.parse_security names its statuses without an order; this projection shows fail first, na "
     "last. class: fail is a failed hardening check (its weight is the check's severity); pass is a measured "
     "check; na is not assessable on this platform or evidence and determines no level.",
     ("fail", "pass", "na"), {"fail": _C_RISK, "pass": _C_PASS, "na": _C_UND}),
    ("security_check_severity", SEC_SEVERITIES, _PRESENTATION_OWNER,
     "rank: parse._SEC_CHECKS weights its checks high, medium, low, with info for checks that carry no "
     "weight; this projection shows them in that order. class: a high-severity check is the weight that "
     "makes the grade weak; "
     "medium and low need attention; info carries no weight and determines no level.",
     SEC_SEVERITIES, {"high": _C_RISK, "medium": _C_WATCH, "low": _C_WATCH, "info": _C_UND}),
    ("coverage_state", COVERAGE_STATE_ORDER, "coverage_matrix.COVERAGE_STATE_ORDER",
     "rank: the owner's evidence-limit precedence for a device rollup, most limited first; it ranks evidence "
     "limits, not risk or health. class: covered is the matrix producer's published verdict (the "
     "coverage_matrix_shown_as_published caveat still applies); partial is observed but incomplete evidence; "
     "every other state is an evidence absence and determines no level.",
     # not_collected, unverified, unparsed, partial, not_observed, covered
     COVERAGE_STATE_ORDER, _classed(COVERAGE_STATE_ORDER, (_C_UND, _C_UND, _C_UND, _C_WATCH, _C_UND, _C_PASS))),
    ("unknown_evidence_state", UNKNOWN_EVIDENCE_STATES, _PRESENTATION_OWNER,
     "rank: unknown_evidence._assemble names its summary states without an order; this projection shows the "
     "least complete first. class: only the two states the owner reaches with every source observed "
     "completely determine a level: no unknowns is acceptable, unresolved unknowns need attention; an "
     "incomplete or unavailable summary determines no level.",
     ("unavailable", "incomplete_with_unresolved", "incomplete", "observed_with_unresolved", "observed_no_unknowns"),
     {"unavailable": _C_UND, "incomplete_with_unresolved": _C_UND, "incomplete": _C_UND,
      "observed_with_unresolved": _C_WATCH, "observed_no_unknowns": _C_PASS}),
    ("unknown_evidence_source_state", UE_SOURCE_STATES, _PRESENTATION_OWNER,
     "rank: unknown_evidence names its source states without an order; this projection shows the least "
     "observed first. class: observed is a completely observed source; partial needs attention; "
     "observed_empty does not satisfy the owner's source_complete predicate, so it vouches for no coverage; "
     "not_collected and malformed are absences and determine no level.",
     # observed, observed_empty, partial, not_collected, malformed
     _ranked_by(UE_SOURCE_STATES, (4, 3, 2, 0, 1)),
     _classed(UE_SOURCE_STATES, (_C_PASS, _C_UND, _C_WATCH, _C_UND, _C_UND))),
    ("stp_root_election_state", STP_ROOT_ELECTION_STATES, _PRESENTATION_OWNER,
     "rank: stp_topology names its election states without an order; this projection shows the "
     "contradiction first, the absence last. class: ambiguous is an observed contradiction between root "
     "claims that needs attention; published is one consistent root claimant; not_observed is an evidence "
     "absence and determines no level.",
     ("ambiguous", "published", "not_observed"), {"ambiguous": _C_WATCH, "published": _C_PASS,
                                                   "not_observed": _C_UND}),
)
#: Every other closed string vocabulary the schema publishes: (name, tokens in schema order, why it carries no
#: level). Evidence states, reasons, roles, names and presentation tokens are not severities; naming each one
#: here keeps the catalogue closed, so a vocabulary added to the schema cannot go unclassified.
_VOCAB_UNRANKED: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("evidence_state", STATES, "the projection's fact-state vocabulary (CensusEmbedded.state); the state "
                               "machinery types it and a page reads the withheld reason, never a level"),
    ("abstention_state", tuple(ssot.ABSTENTION_STATES), "ssot.abstention_reason's codomain (CensusRow.state, "
                                                         "ExposureValue.input_state): an evidence state, not a verdict"),
    ("withheld_state", WITHHELD_STATES, "the withheld branch of every fact: each state names why a value is "
                                        "absent, never how severe it is"),
    ("trust_input_custody", TRUST_INPUT_CUSTODY, "why an analysis input did not assess a listed device "
                                                 "(TrustInputHost.custody): withheld states, each an absence that "
                                                 "names why, never how severe; the gap's weight is its n out of of"),
    ("engine_state", ENGINE_STATES, "the raw owner token an envelope keeps beside a projected state"),
    ("engine_state_owner", ENGINE_STATE_OWNERS, "the owner that produced an engine_state"),
    ("limitation_id", _ALL_LIMITATION_IDS, "the registered qualifications a value may cite; LIMITATIONS and "
                                           "DEVICE_LIMITATIONS carry their text and owner"),
    ("ref_role", REF_ROLES, "the role a snapshot pointer plays in a fact's evidence"),
    ("census_kind", CENSUS_KINDS, "the shape ssot.compute_schema_census observed for a section"),
    ("phase_classification", PHASE_CLASSIFICATIONS, "ssot.failed_sections' classification of a failed phase"),
    ("brief_axis", tuple(AXIS_BASIS), "the executive-brief axis labels (AbsentAxis.axis); an axis carries its "
                                      "severity in its AxisValue, which the severity vocabulary ranks"),
    ("not_assessed_reason", NOT_ASSESSED_REASONS, "why ssot.fleet_avg_health found nothing scored"),
    ("fleet_health_state", FLEET_HEALTH_STATES, "ssot.fleet_avg_health's own state vocabulary"),
    ("lifecycle_fact_name", LIFECYCLE_FACT_NAMES, "the lifecycle summary field that counts each band"),
    ("interface_column", IF_COLUMNS, "the interface table's column names"),
    ("topology_style_token", TOPOLOGY_STYLE_TOKENS, "styled by the topology legend's tone, stroke and weight, "
                                                    "the module's other presentation owner"),
    ("topology_glyph", TOPOLOGY_GLYPHS, "the node glyph shape a style names"),
    ("topology_tone", TOPOLOGY_TONES, "the legend's colour tone; a browser theme chooses the colour"),
    ("topology_stroke", TOPOLOGY_STROKES, "the legend's stroke style"),
    ("topology_weight", TOPOLOGY_WEIGHTS, "the legend's stroke weight"),
    ("dossier_axis", DOSSIER_AXES, "the dossier's exposure axes; each axis carries its state in its ExposureValue"),
    ("coverage_dimension", COVERAGE_DIMENSIONS, "the coverage matrix's dimension of a row"),
    ("coverage_verdict_source", COVERAGE_VERDICT_SOURCES, "the owner that produced a coverage verdict"),
    ("evidence_basis", PUNCH_EVIDENCE_BASES, "how a finding's evidence pointers were produced (record, row or "
                                             "absence witness); the finding's severity carries its level"),
    ("evidence_ref_kind", PUNCH_EVIDENCE_REF_KINDS, "the kind of record an evidence pointer names"),
    ("evidence_ref_role", PUNCH_EVIDENCE_ROLES, "the role an evidence pointer plays for its finding"),
    ("punch_category", FINDING_CATEGORIES, "analyze.PUNCH_CATEGORIES, the punch-list finding categories "
                                           "(CategoryFacetRow.k): what a finding is about; its severity carries "
                                           "its level"),
    ("stp_root_reason", STP_ROOT_REASONS, "why an STP root election reached its state; the state is ranked"),
    ("address_origin", ADDRESS_ORIGINS, "where a topology source address was observed"),
    ("fib_invalid_route_field", FIB_ROUTE_FIELDS, "the route fields a FIB hop reports as invalid"),
    ("fib_mtu_gap_reason", FIB_MTU_GAP_REASONS, "why a FIB hop's MTU was not observed"),
)


def _vocab_title(name: str) -> str:
    return "Vocab" + "".join(part.capitalize() for part in name.split("_"))


def _vocab_order(order: Tuple[Any, ...]) -> Tuple[Tuple[str, ...], ...]:
    return tuple((group,) if isinstance(group, str) else tuple(group) for group in order)


def _vocab() -> Dict[str, Any]:
    """The constant G43 block, built from new containers on every call."""
    ranked = {}
    for name, _tokens, owner, basis, order, classes in _VOCAB_RANKED:
        items = [{"token": token, "rank": rank, "class": classes[token]}
                 for rank, group in enumerate(_vocab_order(order)) for token in group]
        ranked[name] = {"owner": owner, "basis": basis, "items": items}
    unranked = {name: {"basis": basis, "tokens": list(tokens)} for name, tokens, basis in _VOCAB_UNRANKED}
    return {"schema": VOCAB_SCHEMA, "classes": list(VOCAB_CLASSES), "ranked": ranked, "unranked": unranked}


def project(snap: Any) -> Dict[str, Any]:
    """The whole ``ui_projection/1`` payload for one snapshot (device pages are separate documents:
    :func:`project_device`). Pure and total."""
    ctx = _Ctx(snap)
    return {"schema": SCHEMA, "engine": _engine(ctx), "overview": _overview(ctx), "trust": _trust(ctx),
            "inventory": _inventory(ctx), "findings": _findings(ctx), "topology": _topology(ctx),
            "vocab": _vocab()}


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
                     ("risk_band", "RiskBandFact"), ("move_group", _TEXT))
_VLAN_ROW_FACTS = {"vlan": "CountFact", "stp_root_default_election": "FlagFact", "fhrp": "FhrpFact",
                   "stp_root_state": "StpRootStateFact", "stp_root_reason": "StpRootReasonFact",
                   "stp_root_claimants": "TextListFact", "stp_root_identities": "StpRootIdentitiesFact",
                   "gateway_svi_hosts": "TextListFact", "endpoint_count": "CountFact",
                   "dependencies": "TextListFact", "readiness": "ReadinessFact"}
#: G16: one VLAN gateway row (:func:`_gateway_row`); risk is the sole-gateway risk, a boolean.
_VLAN_GATEWAY_CELLS = (("host", _TEXT), ("svi_ip", _TEXT), ("role", _TEXT), ("tracking", _TEXT), ("risk", "FlagFact"))
_ENDPOINT_ROW_CELLS = (("host", _TEXT), ("port", _TEXT), ("mac", _TEXT), ("vlan", _TEXT), ("ip", _TEXT),
                       ("mac_count", "CountFact"), ("vendor", _TEXT), ("endpoint_class", _TEXT),
                       ("confidence", "EndpointConfidenceFact"), ("evidence", _TEXT))
_FINDING_ROW_CELLS = (("priority", "CountFact"), ("rank", "CountFact"), ("severity", "SeverityFact"),
                      ("category", _TEXT), ("title", _TEXT), ("detail", _TEXT), ("devices", "TextListFact"),
                      ("wave", _TEXT), ("remediation", _TEXT), ("severity_basis", _TEXT),
                      ("evidence_confidence", _TEXT), ("source_command", _TEXT),
                      ("evidence_basis", "EvidenceBasisFact"), ("evidence_refs", "EvidenceRefList"),
                      ("evidence_refs_total", "CountFact"), ("evidence_refs_cap", "EvidenceCap"))
#: A cross-layer correlation row (G24): the producer's own fields, then the hosts it names.
_CROSS_LAYER_ROW_CELLS = (("id", _TEXT), ("severity", "SeverityFact"), ("layers", _TEXT), ("title", _TEXT),
                          ("detail", _TEXT), ("recommendation", _TEXT), ("hosts", "CrossLayerHostRowList"))
#: One host a cross-layer row names: the collected device it joins and the health deduction the row drives there.
_CROSS_LAYER_HOST_CELLS = (("host", _TEXT), ("device", "PointerFact"), ("deduction_ref", "EvidenceRefFact"),
                           ("deduction", _TEXT))


def _slice2_defs(defs: Dict[str, Any]) -> None:
    """Inventory, Findings and the device page: typed facts, rows, lists and sections."""
    for name, vocab in (("LifecycleBandFact", LIFECYCLE_BAND_ORDER), ("RiskBandFact", DOSSIER_BANDS),
                        ("SeverityFact", SEVERITIES), ("ReadinessFact", VLAN_READINESS),
                        ("CheckStatusFact", READINESS_CHECK_STATUSES),
                        ("EndpointConfidenceFact", ENDPOINT_CONFIDENCES), ("CollectionStatusFact", CC_STATUSES),
                        ("OpStatusFact", OP_STATUSES), ("EvidenceBasisFact", PUNCH_EVIDENCE_BASES),
                        ("CoverageStateFact", COVERAGE_STATE_ORDER), ("CoverageDimensionFact", COVERAGE_DIMENSIONS),
                        ("CoverageVerdictSourceFact", COVERAGE_VERDICT_SOURCES),
                        ("StpRootStateFact", STP_ROOT_ELECTION_STATES), ("StpRootReasonFact", STP_ROOT_REASONS)):
        defs[name] = _fact_def(name, _enum(vocab))
    defs["EvidenceRefValue"] = _closed("EvidenceRefValue", ("kind", "host", "ref", "role", "cite"),
                                       {"kind": _enum(PUNCH_EVIDENCE_REF_KINDS), "host": _nullable(_str()),
                                        "ref": _ref("Pointer"), "role": _enum(PUNCH_EVIDENCE_ROLES), "cite": _str()})
    defs["EvidenceRefFact"] = _fact_def("EvidenceRefFact", _ref("EvidenceRefValue"))
    defs["EvidenceRefItem"] = _item_def("EvidenceRefItem", "EvidenceRefFact")
    defs["EvidenceRefList"] = _list_def("EvidenceRefList", _ref("EvidenceRefItem"))
    defs["EvidenceCap"] = _closed("EvidenceCap", ("limit", "reached", "total"),
                                  {"limit": {"const": PUNCH_EVIDENCE_REFS_CAP},
                                   "reached": _nullable(_bool()), "total": _ref("CountFact")})
    defs["TextListFact"] = _fact_def("TextListFact", {"type": "array", "items": _str()})
    defs["SeverityCountsFact"] = _fact_def(
        "SeverityCountsFact",
        _closed("SeverityCountsValue", SEVERITIES, {severity: _nonneg_int() for severity in SEVERITIES}),
    )
    defs["DeviceFindingsRollup"] = _closed(
        "DeviceFindingsRollup", ("worst", "by_severity"),
        {"worst": _ref("SeverityFact"), "by_severity": _ref("SeverityCountsFact")},
    )
    defs["DeviceCoverageRollup"] = _closed(
        "DeviceCoverageRollup", ("worst", "n_abstained"),
        {"worst": _ref("CoverageStateFact"), "n_abstained": _ref("CountFact")},
    )
    defs["ReadinessCheckRow"] = _row_def("ReadinessCheckRow", _indexed(),
                                          (("check", _TEXT), ("status", "CheckStatusFact"),
                                           ("note", _TEXT), ("phase", _TEXT)))
    defs["ReadinessCheckList"] = _list_def("ReadinessCheckList", _ref("ReadinessCheckRow"))
    defs["ReadinessGroupRow"] = _row_def("ReadinessGroupRow", _indexed(),
                                          (("group", _TEXT), ("readiness", "ReadinessFact"),
                                           ("switches", "TextListFact"), ("endpoints", "CountFact"),
                                           ("n_fail", "CountFact"), ("n_warn", "CountFact")),
                                          {"checks": _ref("ReadinessCheckList")})
    defs["ReadinessGroupList"] = _list_def("ReadinessGroupList", _ref("ReadinessGroupRow"))
    defs["Readiness"] = _closed("Readiness", ("groups",), {"groups": _ref("ReadinessGroupList")})
    defs["HealthBandRow"] = _row_def("HealthBandRow", {"band": _enum(HEALTH_BANDS + (HEALTH_BAND_NOT_SCORED,))},
                                      (("n", "CountFact"), ("hosts", "TextListFact")))
    priority = {"type": "integer", "minimum": -JS_MAX_SAFE_INT, "maximum": JS_MAX_SAFE_INT}
    defs["StpRootIdentity"] = _closed("StpRootIdentity", (
        "root_address", "root_priority", "root_priorities", "claimants", "observers"), {
        "root_address": _str(), "root_priority": _nullable(priority),
        "root_priorities": {"type": "array", "items": priority},
        "claimants": {"type": "array", "items": _str()}, "observers": {"type": "array", "items": _str()}})
    defs["StpRootIdentitiesFact"] = _fact_def("StpRootIdentitiesFact", {
        "type": "array", "items": _ref("StpRootIdentity")})
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
    defs["CoverageItem"] = _closed("CoverageItem", ("axis", "pointer", "fact", "dimension", "verdict_source",
                                                   "is_abstention"),
                                   {"axis": _str(), "pointer": _ref("Pointer"), "fact": _ref("CoverageCellFact"),
                                    "dimension": _ref("CoverageDimensionFact"),
                                    "verdict_source": _ref("CoverageVerdictSourceFact"),
                                    "is_abstention": _ref("FlagFact")})
    defs["DeviceRosters"] = _closed("DeviceRosters", ("devices", "collection_completeness"),
                                    {"devices": _bool(), "collection_completeness": _bool()})
    defs["DeviceRowRefs"] = _closed("DeviceRowRefs", ("health", "lifecycle", "dossier", "collection"),
                                    {k: _nullable(_ref("Pointer")) for k in ("health", "lifecycle", "dossier",
                                                                             "collection")})
    defs["DeviceRow"] = _row_def("DeviceRow", {"host": _str(), "pointer": _nullable(_ref("Pointer")),
                                               "rosters": _ref("DeviceRosters"), "rows": _ref("DeviceRowRefs"),
                                               "findings": _ref("DeviceFindingsRollup"),
                                               "coverage": _ref("DeviceCoverageRollup")},
                                 _DEVICE_ROW_CELLS)
    defs["VlanGatewayRow"] = _row_def("VlanGatewayRow", _indexed(), _VLAN_GATEWAY_CELLS)
    defs["StpRootObservation"] = _row_def("StpRootObservation", {"host": _str(), "pointer": _ref("Pointer")},
                                          (("is_root", "FlagFact"), ("root_address", "TextFact"),
                                           ("root_priority", "CountFact")))
    defs["StpRootObservationList"] = _list_def("StpRootObservationList", _ref("StpRootObservation"))
    defs["VlanSelections"] = _closed("VlanSelections", ("stp_roots", "gateways", "endpoints"),
                                     {"stp_roots": _ref("StpRootObservationList"),
                                      "gateways": _ref("VlanGatewayRowList"),
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
    defs["PointerFact"] = _fact_def("PointerFact", _ref("Pointer"))
    defs["CrossLayerHostRow"] = _row_def("CrossLayerHostRow", _indexed(), _CROSS_LAYER_HOST_CELLS)
    defs["CrossLayerHostRowList"] = _list_def("CrossLayerHostRowList", _ref("CrossLayerHostRow"))
    defs["CrossLayerRow"] = _row_def("CrossLayerRow", _indexed(), _CROSS_LAYER_ROW_CELLS)
    defs["CrossLayerRowList"] = _list_def("CrossLayerRowList", _ref("CrossLayerRow"))
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
                                                                                          "as", "peer_host")))
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
    for title, item in (("DeviceRowList", "DeviceRow"), ("VlanRowList", "VlanRow"),
                        ("VlanGatewayRowList", "VlanGatewayRow"), ("EndpointRowList", "EndpointRow"),
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
    # G21: one closed bucket per owner vocabulary key, in owner order; the device facet follows the inventory roster.
    defs["SeverityFacetRow"] = _closed("SeverityFacetRow", ("k", "n"), {"k": _enum(SEVERITIES), "n": _ref("CountFact")})
    defs["CategoryFacetRow"] = _closed("CategoryFacetRow", ("k", "n"),
                                       {"k": _enum(FINDING_CATEGORIES), "n": _ref("CountFact")})
    defs["DeviceFacetRow"] = _closed("DeviceFacetRow", ("k", "n"), {"k": _str(), "n": _ref("CountFact")})
    # The device facet is a roster list with its own state (an absent roster is withheld, never an empty array), so
    # the transport pages it like every other primary list.
    defs["DeviceFacetList"] = _list_def("DeviceFacetList", _ref("DeviceFacetRow"))
    n_severities, n_categories = len(SEVERITIES), len(FINDING_CATEGORIES)
    defs["FindingFacets"] = _closed("FindingFacets", FINDING_FACETS, {
        "severity": {"type": "array", "minItems": n_severities, "maxItems": n_severities,
                     "items": _ref("SeverityFacetRow")},
        "category": {"type": "array", "minItems": n_categories, "maxItems": n_categories,
                     "items": _ref("CategoryFacetRow")},
        "device": _ref("DeviceFacetList")})
    defs["Findings"] = _closed("Findings", ("total", "headline_axis_index", "rows", "facets",
                                           "cross_layer"),
                               {"total": _ref("CountFact"), "headline_axis_index": _nullable(_nonneg_int()),
                                "rows": _ref("FindingRowList"), "facets": _ref("FindingFacets"),
                                "cross_layer": _ref("CrossLayerRowList")})
    identity = _closed("DeviceIdentity", IDENTITY_FIELDS, {f: _ref(_TEXT) for f in IDENTITY_FIELDS})
    physical_props = {**{f: _ref("CountFact") for f in DEVICE_PHYSICAL_ZERO_DEFAULTS + ("active_ports",)},
                      **{f: _ref(_TEXT) for f in PHYSICAL_TEXT_FIELDS}}
    n_lims = len(_DEVICE_DOC_LIMITATIONS)
    defs["DevicePage"] = _closed("DevicePage", (
        "host", "rosters", "identity", "physical", "collection", "health", "lifecycle", "dossier", "coverage",
        "interfaces", "links", "routes", "routing_neighbors", "security", "native_vlan_mismatches", "remediation",
        "nrfu_cases", "findings", "endpoints", "limitations", "move_group", "findings_rollup", "coverage_rollup",
        "failure_impact", "structural_links"), {
        "host": _nullable(_str()),
        "move_group": _ref(_TEXT),
        "findings_rollup": _ref("DeviceFindingsRollup"),
        "coverage_rollup": _ref("DeviceCoverageRollup"),
        "rosters": _closed("DevicePageRosters", ("devices", "collection_completeness", "cable_map"),
                           {"devices": _bool(), "collection_completeness": _bool(), "cable_map": _bool()}),
        "identity": identity,
        "physical": _closed("DevicePhysical", tuple(physical_props), physical_props),
        "collection": _closed("DeviceCollection", ("status", "data_quality", "missing"),
                              {"status": _ref("CollectionStatusFact"), "data_quality": _ref("ScoreFact"),
                               "missing": _ref("TextListFact")}),
        "health": _closed("DeviceHealth", ("score", "band", "role", "deductions", "deductions_cap",
                                            "deduction_refs", "deduction_refs_cap"),
                          {"score": _ref("ScoreFact"), "band": _ref("BandFact"), "role": _ref(_TEXT),
                           "deductions": _ref("TextItemList"), "deductions_cap": _ref("Cap"),
                           "deduction_refs": _ref("EvidenceRefList"), "deduction_refs_cap": _ref("Cap")}),
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
        "failure_impact": _ref("TopologyImpactRowList"), "structural_links": _ref("TopologyStructuralLinkRowList"),
        "limitations": {"type": "array", "minItems": n_lims, "maxItems": n_lims, "items": _ref("Limitation")},
    })
    defs["DeviceDocument"] = _closed("DeviceDocument", ("schema", "engine", "device", "vocab"),
                                     {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"),
                                      "device": _ref("DevicePage"), "vocab": _ref("Vocab")})


def _topology_defs(defs: Dict[str, Any]) -> None:
    defs["TopologyStyleValue"] = _closed("TopologyStyleValue", ("token", "glyph", "label"),
        {"token": _enum(TOPOLOGY_STYLE_TOKENS), "glyph": _enum(TOPOLOGY_GLYPHS), "label": _str()})
    defs["TopologyStyleFact"] = _fact_def("TopologyStyleFact", _ref("TopologyStyleValue"))
    defs["TopologyLegendEntry"] = _closed("TopologyLegendEntry", ("token", "tone", "stroke", "weight", "meaning"),
        {"token": _enum(TOPOLOGY_STYLE_TOKENS), "tone": _enum(TOPOLOGY_TONES),
         "stroke": _enum(TOPOLOGY_STROKES), "weight": _enum(TOPOLOGY_WEIGHTS), "meaning": _str()})
    defs["TopologyLegend"] = _closed("TopologyLegend", ("schema", "entries", "fallback"),
        {"schema": {"const": TOPOLOGY_STYLE_SCHEMA}, "entries": {
            "type": "array", "minItems": len(TOPOLOGY_STYLE_TOKENS), "maxItems": len(TOPOLOGY_STYLE_TOKENS),
            "items": _ref("TopologyLegendEntry")}, "fallback": _ref("TopologyStyleValue")})
    defs["StructuralEndsFact"] = _fact_def("StructuralEndsFact", _closed("StructuralEnds",
        ("a_host", "a_port", "b_host", "b_port"), {k: _str() for k in ("a_host", "a_port", "b_host", "b_port")}))
    defs["NonnegativeNumberFact"] = _fact_def("NonnegativeNumberFact", {"type": "number", "minimum": 0,
                                                                                   "maximum": JS_MAX_SAFE_INT})
    defs["PositiveCountFact"] = _fact_def("PositiveCountFact", {**_nonneg_int(), "minimum": 1})
    defs["ImpactSeverityFact"] = _fact_def("ImpactSeverityFact", _enum(IMPACT_SEVERITIES))
    defs["AddressFamilyFact"] = _fact_def("AddressFamilyFact", {"type": "integer", "enum": [4, 6]})
    defs["AddressOriginFact"] = _fact_def("AddressOriginFact", _enum(ADDRESS_ORIGINS))
    rows = {
        "TopologyNodeRow": (("host", "TextFact"), ("kind", "TextFact"), ("role", "TextFact"),
                            ("collected", "FlagFact"), ("style", "TopologyStyleFact")),
        "TopologyCableMemberRow": (("a_port", "TextFact"), ("b_port", "TextFact")),
        "TopologyCableRow": (("ends", "CableEndsFact"), ("members", "TopologyCableMemberRowList"),
                             ("speed", "TextFact"), ("confirmation", "TextFact"), ("op_status", "OpStatusFact"),
                             ("a_nodes", "RowRefList"), ("b_nodes", "RowRefList"), ("style", "TopologyStyleFact")),
        "TopologyStructuralLinkRow": (("ends", "StructuralEndsFact"), ("betweenness", "NonnegativeNumberFact"),
                                      ("is_bridge", "FlagFact"), ("pairs_cut", "CountFact"), ("rank", "PositiveCountFact"),
                                      ("a_nodes", "RowRefList"), ("b_nodes", "RowRefList"),
                                      ("host_pair_cable_refs", "RowRefList"), ("style", "TopologyStyleFact")),
        "TopologyImpactRow": (("host", "TextFact"), ("node_refs", "RowRefList"), ("severity", "ImpactSeverityFact"),
                              *((k, "CountFact") for k in ("vlans_impacted", "stranded", "hard", "backup", "fhrp", "off_scan_gw_vlans")),
                              ("detail", "TextFact"), ("style", "TopologyStyleFact")),
        "TopologyAddressRow": (("host", "TextFact"), ("interface", "TextFact"), ("address", "TextFact"),
                               ("family", "AddressFamilyFact"), ("origin", "AddressOriginFact"), ("node_refs", "RowRefList")),
    }
    for name, cells in rows.items():
        defs[name] = _row_def(name, _indexed(), cells)
        defs[name + "List"] = _list_def(name + "List", _ref(name))
    props = {"summary": _closed("TopologySummary", ("nodes", "cables"),
                                 {k: _ref("CountFact") for k in ("nodes", "cables")})}
    props.update({k: _ref(v + "List") for k, v in (
        ("nodes", "TopologyNodeRow"), ("cables", "TopologyCableRow"),
        ("structural_links", "TopologyStructuralLinkRow"), ("failure_impact", "TopologyImpactRow"),
        ("source_addresses", "TopologyAddressRow"))})
    props["legend"] = _ref("TopologyLegend")
    defs["Topology"] = _closed("Topology", tuple(props), props)
    hop_fields = ("host", "match", "next_hop", "out_intf", "source")
    defs["FibHop"] = _closed("FibHop", hop_fields, {**{k: _str() for k in hop_fields},
        "invalid_route_fields": {"type": "array", "minItems": 1, "items": _enum(FIB_ROUTE_FIELDS)}})
    array_hops = {"type": "array", "items": _ref("FibHop")}
    leg_fields = ("host", "match", "next_hop", "out_intf", "leg_status", "drop_evidence", "resolved_hops")
    defs["FibDroppingLeg"] = _closed("FibDroppingLeg", leg_fields,
        {**{k: _str() for k in leg_fields[:-1]}, "resolved_hops": array_hops})
    defs["FibCandidateSet"] = _closed("FibCandidateSet", ("kind", "candidate_hosts"),
        {"kind": _str(), "candidate_hosts": {"type": "array", "items": _str()}})
    defs["FibMtuHop"] = _closed("FibMtuHop", ("host", "out_intf", "mtu"),
        {"host": _str(), "out_intf": _str(), "mtu": _nonneg_int()})
    defs["FibMtuGap"] = _closed("FibMtuGap", ("host", "out_intf"),
        {"host": _str(), "out_intf": _str(), "reason": _enum(FIB_MTU_GAP_REASONS)})
    defs["FibJumboBlackhole"] = _closed("FibJumboBlackhole", ("host", "out_intf", "mtu", "required"),
        {"host": _str(), "out_intf": _str(), "mtu": _nonneg_int(), "required": _nonneg_int()})
    props = {k: _str() for k in ("src", "dst", "status", "drop_evidence", "mtu_verdict")}
    props.update({"hops": array_hops, "computed": _bool(), "reached": _bool(),
                  "mtu_min": _nullable(_nonneg_int()), "mtu_bottleneck_hop": _nullable(_ref("FibMtuHop"))})
    props.update({k: {"type": "array", "items": _ref(v)} for k, v in (
        ("ecmp_dropping_legs", "FibDroppingLeg"), ("ambiguous_candidate_sets", "FibCandidateSet"),
        ("mtu_unobserved_hops", "FibMtuGap"), ("jumbo_blackhole", "FibJumboBlackhole"))})
    defs["FibResult"] = _closed("FibResult", tuple(props), props)
    defs["FibResultFact"] = _fact_def("FibResultFact", _ref("FibResult"))
    defs["PathInterfaceRefList"] = _list_def("PathInterfaceRefList", _ref("Ref"))
    defs["PathHopEvidence"] = _closed("PathHopEvidence", ("hop_index", "route_rows", "interfaces", "node_rows"),
        {"hop_index": _nonneg_int(), "route_rows": _ref("RowRefList"), "interfaces": _ref("PathInterfaceRefList"),
         "node_rows": _ref("RowRefList")})
    defs["PathHopEvidenceList"] = _list_def("PathHopEvidenceList", _ref("PathHopEvidence"))
    defs["PathQuery"] = _closed("PathQuery", ("src_ip", "dst_ip", "max_hops", "required_mtu", "disclose"),
        {"src_ip": _str(), "dst_ip": _str(), "max_hops": {"type": "integer", "const": 32},
         "required_mtu": _null(), "disclose": {"type": "boolean", "const": True}})
    defs["Path"] = _closed("Path", ("query", "result", "hop_evidence", "style", "legend"),
        {"query": _ref("PathQuery"), "result": _ref("FibResultFact"), "hop_evidence": _ref("PathHopEvidenceList"),
         "style": _ref("TopologyStyleFact"), "legend": _ref("TopologyLegend")})
    defs["PathDocument"] = _closed("PathDocument", ("schema", "engine", "path", "vocab"),
        {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"), "path": _ref("Path"),
         "vocab": _ref("Vocab")})


def _vocab_defs(defs: Dict[str, Any]) -> None:
    """The G43 block: a closed item schema per ranked vocabulary, its token enum that vocabulary's own."""
    defs["VocabClass"] = {"title": "VocabClass", "type": "string", "enum": list(VOCAB_CLASSES)}
    text = {"type": "string", "minLength": 1}
    ranked: Dict[str, Any] = {}
    for name, tokens, _owner, _basis, order, classes in _VOCAB_RANKED:
        groups = _vocab_order(order)
        ordered = [token for group in groups for token in group]
        if (sorted(ordered) != sorted(tokens) or len(set(ordered)) != len(tokens) or set(classes) != set(tokens)
                or not set(classes.values()) <= set(VOCAB_CLASSES)):
            raise ValueError(f"vocab {name}: its order or classes do not cover its tokens exactly once")
        item = _vocab_title(name) + "Item"
        defs[item] = _closed(item, ("token", "rank", "class"),
                             {"token": _enum(tokens), "class": _ref("VocabClass"),
                              "rank": {"type": "integer", "minimum": 0, "maximum": len(groups) - 1}})
        ranked[name] = _closed(_vocab_title(name), ("owner", "basis", "items"),
                               {"owner": dict(text), "basis": dict(text),
                                "items": {"type": "array", "minItems": len(tokens), "maxItems": len(tokens),
                                          "items": _ref(item)}})
    defs["VocabRanked"] = _closed("VocabRanked", tuple(ranked), ranked)
    unranked = {name: _closed(_vocab_title(name), ("basis", "tokens"),
                              {"basis": dict(text), "tokens": {"type": "array", "uniqueItems": True,
                                                              "items": _enum(tokens)}})
                for name, tokens, _basis in _VOCAB_UNRANKED}
    defs["VocabUnranked"] = _closed("VocabUnranked", tuple(unranked), unranked)
    n_classes = len(VOCAB_CLASSES)
    defs["Vocab"] = _closed("Vocab", ("schema", "classes", "ranked", "unranked"),
                            {"schema": {"type": "string", "const": VOCAB_SCHEMA},
                             "classes": {"type": "array", "minItems": n_classes, "maxItems": n_classes,
                                         "items": _ref("VocabClass")},
                             "ranked": _ref("VocabRanked"), "unranked": _ref("VocabUnranked")})


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
        "AxisUnassessed": _closed("AxisUnassessed", ("n", "of"), {"n": _ref("CountFact"), "of": _ref("CountFact")}),
        "AxisItem": _closed("AxisItem", ("index", "axis", "basis_sections", "fact", "unassessed"),
                            {"index": _nonneg_int(), "axis": _nullable(_str()),
                             "basis_sections": {"type": "array", "items": _str()}, "fact": _ref("AxisFact"),
                             "unassessed": _ref("AxisUnassessed")}),
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
                                  "fact_name": {"type": "string", "enum": list(LIFECYCLE_FACT_NAMES)},
                                  "rank": {"type": "integer", "minimum": 0,
                                           "maximum": len(LIFECYCLE_BAND_ORDER) - 1}}),
    }
    defs["AxisList"] = _list_def("AxisList", _ref("AxisItem"))
    defs["TopGatingList"] = _list_def("TopGatingList", _ref("TopGatingItem"))
    defs["SourceList"] = _list_def("SourceList", _ref("SourceItem"))
    defs["CensusRowList"] = _list_def("CensusRowList", _ref("CensusRow"))
    defs["FailureRecordList"] = _list_def("FailureRecordList", _ref("FailureRecordItem"))
    defs["ViolationList"] = _list_def("ViolationList", _str())
    defs["Sha256Fact"] = _fact_def("Sha256Fact", {"type": "string", "pattern": SNAPSHOT_SHA256_PATTERN})
    defs["Engine"] = _closed(
        "Engine", ("snapshot_schema", "script_version", "generated_at", "collected_at", "snapshot_schema_supported",
                   "code_schema_version", "snapshot_sha256", "snapshot_bytes", "snapshot_digest_form"),
        {"snapshot_schema": _ref("TextFact"), "script_version": _ref("TextFact"), "generated_at": _ref("TextFact"),
         "collected_at": _ref("TextFact"), "snapshot_schema_supported": _nullable({"type": "boolean"}),
         "code_schema_version": _str(), "snapshot_sha256": _ref("Sha256Fact"),
         "snapshot_bytes": _ref("PositiveCountFact"),
         "snapshot_digest_form": {"type": "string", "const": SNAPSHOT_DIGEST_FORM}})
    defs["OverviewFacts"] = _closed(
        "OverviewFacts", tuple(ssot.CANONICAL_FACTS),
        {name: _ref("CanonBand" if name == "worst_band" else "CanonScore" if name == "avg_health" else "CanonCount")
         for name in ssot.CANONICAL_FACTS})
    fh_common = {"engine_state": {"type": "string", "enum": list(FLEET_HEALTH_STATES)},
                 "n_scored": _ref("CountFact"), "n_rows": _ref("CountFact"),
                 "bands": {"type": "array", "minItems": len(HEALTH_BANDS) + 1,
                           "maxItems": len(HEALTH_BANDS) + 1, "items": _ref("HealthBandRow")}}
    fh_required = ["state", "engine_state", "not_assessed_reason", "n_scored", "n_rows", "bands"]
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
        "Overview", ("facts", "fleet_health", "readiness", "axes", "absent_axes", "posture_statement", "top_gating", "lifecycle"),
        {"facts": _ref("OverviewFacts"), "fleet_health": _ref("FleetHealth"), "axes": _ref("AxisList"),
         "readiness": _ref("Readiness"),
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
    defs["TrustInputHost"] = _closed(
        "TrustInputHost", ("host", "custody", "label", "pointer"),
        {"host": _str(), "custody": _enum(TRUST_INPUT_CUSTODY), "label": _nullable(_str()),
         "pointer": _ref("Pointer")})
    defs["TrustInputHostList"] = _list_def("TrustInputHostList", _ref("TrustInputHost"))
    defs["TrustInput"] = _closed(
        "TrustInput", ("input", "sections", "n", "of", "hosts"),
        {"input": _enum(tuple(TRUST_INPUTS)), "sections": {"type": "array", "items": _str()},
         "n": _ref("CountFact"), "of": _ref("CountFact"), "hosts": _ref("TrustInputHostList")})
    n_lims = len(LIMITATIONS)
    n_inputs = len(TRUST_INPUTS)
    defs["Trust"] = _closed(
        "Trust", ("census", "failures", "coverage_matrix", "unknown_evidence", "ssot", "inputs", "limitations"),
        {"census": _ref("Census"), "failures": _ref("Failures"), "coverage_matrix": _ref("CoverageMatrix"),
         "unknown_evidence": _ref("UnknownEvidence"), "ssot": _ref("Ssot"),
         "inputs": {"type": "array", "minItems": n_inputs, "maxItems": n_inputs, "items": _ref("TrustInput")},
         "limitations": {"type": "array", "minItems": n_lims, "maxItems": n_lims, "items": _ref("Limitation")}})
    _slice2_defs(defs)
    _topology_defs(defs)
    _vocab_defs(defs)
    root = _closed("UiProjection",
                   ("schema", "engine", "overview", "trust", "inventory", "findings", "topology", "vocab"),
                   {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"),
                    "overview": _ref("Overview"), "trust": _ref("Trust"), "inventory": _ref("Inventory"),
                    "findings": _ref("Findings"), "topology": _ref("Topology"), "vocab": _ref("Vocab")})
    root["title"] = SCHEMA
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **root, "$defs": defs}


def ui_projection_schema() -> Dict[str, Any]:
    """The ``ui_projection/1`` JSON Schema (draft 2020-12), built fresh on every call (no shared nodes)."""
    return _copy_schema(_build_schema())


__all__ = [
    "ALWAYS_EMITTED_AXES", "ANALYSIS_SECTIONS", "APP_DOMAIN_JOINER", "AXIS_BASIS", "AXIS_UNASSESSED",
    "AXIS_UNASSESSED_ABSENT", "AXIS_UNASSESSED_LAYERS", "AXIS_UNASSESSED_LIVE", "AXIS_UNASSESSED_SPARSE",
    "BRIEF_INPUTS", "CC_STATUSES",
    "CENSUS_KINDS", "COVERAGE_STATES", "CROSS_LAYER_INPUTS", "DEVICE_CITED_LIMITATIONS", "DEVICE_LIMITATIONS", "DEVICE_PHYSICAL_TEXT",
    "DEVICE_PHYSICAL_ZERO_DEFAULTS", "DOMAIN_STATE_OWNERS", "DOSSIER_BANDS", "DOSSIER_UNDERSTATABLE",
    "ENDPOINT_CONFIDENCES", "ENGINE_LIST_CAPS", "ENGINE_STATES", "ENGINE_STATE_OWNERS", "ESSENTIAL_LABELS",
    "EXPOSURE_STATES", "FLEET_HEALTH_STATES", "HEALTH_BANDS", "HEALTH_BAND_NOT_SCORED", "IDENTITY_FIELDS",
    "IF_COLUMNS", "JS_MAX_SAFE_INT", "LIFECYCLE_BAND_FACTS", "LIFECYCLE_BAND_FACTS_BY_BAND", "LIFECYCLE_BAND_ORDER",
    "LIMITATIONS", "MOVE_GROUP_LABEL", "NOT_ASSESSED_REASONS", "NOT_OBSERVED_SENTINEL", "NRFU_NOT_OBSERVED",
    "OP_STATUSES", "PHASE_CLASSIFICATIONS", "PHYSICAL_TEXT_FIELDS", "POSTURE_STATEMENT_BASIS", "PUNCHLIST_INPUTS",
    "READINESS_CHECK_STATUSES", "READINESS_INPUTS",
    "PUNCH_BASIS_UNPUBLISHED", "PUNCH_CONFIDENCE_UNPUBLISHED", "PUNCH_DETAIL_CLIP_MARKER", "PUNCH_RANK",
    "RECONCILED_PATHS", "REF_ROLES", "SCHEMA", "SCHEMA_ID", "SEC_GRADES", "SEC_SEVERITIES", "SEC_STATUSES",
    "SELECTION_NEEDS", "SEVERITIES", "SNAPSHOT_SCHEMA", "STATES", "UE_COMPLETE_STATES", "UE_SOURCE_STATES",
    "UNKNOWN_EVIDENCE_STATES", "VLAN_FIELD_BASIS", "VLAN_READINESS", "WITHHELD_STATES", "json_pointer", "project",
    "project_device", "project_devices", "project_engine", "project_findings", "project_inventory",
    "project_overview", "project_trust", "project_topology", "project_path", "ui_projection_schema",
    "fleet_blind_spot_rows",
    "TOPOLOGY_STYLE_SCHEMA", "TOPOLOGY_STYLE_TOKENS", "TOPOLOGY_GLYPHS", "IMPACT_SEVERITIES", "ADDRESS_ORIGINS",
    "IMPACT_INDETERMINATE_PREFIX", "L3_RISK_CLEAR", "L3_RISK_FLAGS", "L3_RISK_JOINER", "L3_RISK_TRACKING_NOT_ASSESSED",
    "L3_NO_FHRP_FLAG", "L3_SOLE_GATEWAY_FLAG", "L3_TRACKED_DOWN_FLAG", "VLAN_SOLE_GATEWAY_FHRP",
    "TOPOLOGY_TONES", "TOPOLOGY_STROKES", "TOPOLOGY_WEIGHTS", "FIB_ROUTE_FIELDS", "FIB_MTU_GAP_REASONS",
    "LIFECYCLE_FACT_NAMES", "VOCAB_SCHEMA", "VOCAB_CLASSES", "NEIGHBOR_ADDRESS_FIELDS",
    "SNAPSHOT_IDENTITY_OWNER", "SNAPSHOT_SHA256_PATTERN", "SNAPSHOT_DIGEST_FORM",
    "FINDING_CATEGORIES", "FINDING_FACETS", "CATEGORY_SOURCE_KINDS",
]
