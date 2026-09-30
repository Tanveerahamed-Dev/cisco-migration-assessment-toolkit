"""Single source of truth (SSOT) for the assessment's canonical headline facts.

The engine computes each headline fact ONCE during snapshot assembly and publishes it in a
canonical block:

    executive_brief.scale      -> n_devices / n_collected / n_endpoints / n_vlans / n_domains
    executive_brief.posture    -> avg_health / n_critical / n_poor / worst_band
    lifecycle_risk.summary     -> n_past_ldos / n_past_eos / n_near / n_active (+ by_band)
    design_blueprint.summary   -> n_decisions

EVERY downstream surface -- the DOCX/PPTX/XLSX deliverables, the HTML explorer, and the web
dashboard -- must READ those canonical fields, never recompute them from the raw arrays and
never conflate a sibling field. This module is the one place that

  * names the canonical facts (:data:`CANONICAL_FACTS`),
  * reads them canonical-first (:func:`canonical_facts`), and
  * proves each published value still matches an independent derivation from the raw evidence
    (:func:`reconcile`) -- the producer-side guard that catches drift the moment it appears,
    instead of a client noticing a wrong number in a rendered deliverable.

The recurring drift class this exists to kill (it cost several audit waves to find by hand, one
surface at a time across crd/runbook/engagement/deck): a surface reads
``lifecycle_risk.summary.n_past_eos`` (0 on the Meridian reference fleet) where it means the *past-support*
population, which is ``n_past_ldos`` (152) -- silently dropping 152 end-of-support devices into a
false "healthy" reading. The near-twin: ``len(devices)`` / ``len(health_scores)`` used as a
reported device count instead of ``executive_brief.scale.n_devices``.

Read-only and side-effect free: this module derives, it never mutates the snapshot.
"""
from __future__ import annotations

import math
import reprlib
from fractions import Fraction
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from .textutils import is_finite_num   # shared finite-number filter (rejects Infinity/NaN AND the huge int)

# Canonical facts: name -> (dotted snapshot path of the published value, one-line concept).
# The dotted path is the SINGLE authoritative source; anything else reporting the same concept
# must agree with it. Kept as data so tests (and future surfaces) can iterate the contract.
CANONICAL_FACTS: Dict[str, tuple] = {
    "n_devices":          ("executive_brief.scale.n_devices",     "inventoried devices (== len(health_scores))"),
    "n_collected":        ("executive_brief.scale.n_collected",   "devices with a complete collection"),
    "n_endpoints":        ("executive_brief.scale.n_endpoints",   "evidenced endpoints (== len(endpoint_identity))"),
    "n_vlans":            ("executive_brief.scale.n_vlans",       "VLANs in use (== len(analyze.vlan_inventory))"),
    "n_domains":          ("executive_brief.scale.n_domains",     "broadcast/management domains"),
    "avg_health":         ("executive_brief.posture.avg_health",  "mean fleet health score"),
    "n_critical":         ("executive_brief.posture.n_critical",  "devices in the Critical health band"),
    "n_poor":             ("executive_brief.posture.n_poor",      "devices in the Poor health band"),
    "worst_band":         ("executive_brief.posture.worst_band",  "worst health band observed"),
    "n_past_ldos":        ("lifecycle_risk.summary.n_past_ldos",  "devices past last-day-of-support (the past-SUPPORT population)"),
    "n_near":             ("lifecycle_risk.summary.n_near",       "devices within 1yr of LDoS (Near-LDoS band)"),
    "n_past_eos":         ("lifecycle_risk.summary.n_past_eos",   "devices past end-of-sale but NOT yet past LDoS (a disjoint date-band population)"),
    "n_active":           ("lifecycle_risk.summary.n_active",     "devices in the pre-EoS date-position band (public schema value: Active; not a support-entitlement claim)"),
    # The COVERAGE slot. Without it there was no canonical way to say "not determined", and every
    # consumer of n_past_ldos rendered a bare 0 for a fleet nothing had assessed — including the
    # "At a Glance" front matter of every deliverable. A band count that omits Unknown is not a
    # partition of the fleet, and the omission reads as health.
    "n_unknown":          ("lifecycle_risk.summary.n_unknown",    "devices whose support state was NOT determined (no exact EoX row matched or matched source/date authority was withheld) — absence of a finding, never a clean result"),
    "n_design_decisions": ("design_blueprint.summary.n_decisions","ranked target-state design decisions"),
}

# Health-band labels (from analyze.compute_health_scores) and lifecycle-band labels (from
# analyze.lifecycle_risk per_device). Named here so the reconciliation derivation can't silently
# drift from the producer's band vocabulary.
_HEALTH_BAND_CRITICAL = "Critical"
_HEALTH_BAND_POOR = "Poor"
# Worst-band severity order, mirroring analyze.compute_executive_brief: the most-severe band that
# is PRESENT in health_scores wins. "Insufficient Data" is intentionally absent -- it never counts
# as the worst health band, and the avg-health mean excludes it too.
_HEALTH_BAND_ORDER = ("Critical", "Poor", "Fair", "Good", "Excellent")
_HEALTH_BAND_NOT_SCORED = "Insufficient Data"
# Every band a health row can carry (analyze._HEALTH_BANDS labels + the unscored band). A row whose band is
# outside it -- a malformed or uploaded row, or a row that is not a record at all -- could be ANY band, so
# no band count or worst band published over it can be confirmed (see reconcile). Held equal to the
# producer's vocabulary by tests/test_ssot_owner_robustness.py.
_HEALTH_BAND_VOCABULARY: FrozenSet[str] = frozenset(_HEALTH_BAND_ORDER + (_HEALTH_BAND_NOT_SCORED,))
# EVERY band analyze.compute_lifecycle_risk can emit (analyze._LIFECYCLE_BAND_RANK is the producer's
# vocabulary: Past-LDoS / Near-LDoS / Past-EoS / Active / Unknown) mapped to the summary field that
# counts it. "Unknown" was the one omission, and it was the worst possible one: n_unknown is a
# registered CANONICAL_FACT, so it is published, cited and rendered -- but with no entry here it had
# NO raw-basis guard, and reconcile() silently accepted any value. Measured: mutating
# summary.n_unknown from 2 to 99 returned reconcile() == [] while the same mutation to n_past_ldos
# was caught. The one canonical fact whose whole job is to say "not determined" was the only
# lifecycle fact nothing verified. Completeness against the producer's vocabulary is asserted by
# tests/test_ssot_registry.py -- a new band cannot be added upstream without a guard here.
_LIFECYCLE_BANDS = {
    "n_past_ldos": "Past-LDoS",
    "n_past_eos": "Past-EoS",
    "n_near": "Near-LDoS",
    "n_active": "Active",
    "n_unknown": "Unknown",
}


def _as_int(value: Any) -> Optional[int]:
    """Best-effort int coercion; None on anything non-numeric (coverage-honest, never guesses 0)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # inf / NaN are not a coverage-honest count -> None (int(float('inf')) raises OverflowError, int(NaN)
        # raises ValueError; json.loads accepts a bare Infinity/NaN, so both reach here from an upload).
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        try:
            f = float(s)
        except (ValueError, TypeError):
            return None
        return int(f) if math.isfinite(f) else None   # a string that floats to inf (e.g. '1e400') -> None, not OverflowError
    return None


def _as_dict(value: Any) -> Dict[str, Any]:
    """Coerce a possibly-malformed snapshot block to a dict; a truthy non-dict degrades to ``{}``.

    The ``_dotted(...) or {}`` idiom guards ``None``/empty but NOT a *truthy* non-dict (a ``str`` or
    ``list`` from a poisoned or hand-edited ``--no-collect`` snapshot): it keeps the bad value, and the
    first ``.get`` on it then raises ``AttributeError`` -- crashing :func:`reconcile` / :func:`summary`
    and, through ``docmeta.add_excellence_front``, every deliverable generator. Coverage-honest: a
    malformed block reads as 'absent' (its checks skip, no number is fabricated), never a crash.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    """Coerce a possibly-malformed snapshot block to a list; a truthy non-list degrades to ``[]``.

    The list twin of :func:`_as_dict`. The ``... or []`` idiom guards ``None``/empty but NOT a
    *truthy* non-list (an ``int``/``str``/``dict``/``bool`` from a poisoned or hand-edited
    ``--no-collect`` snapshot): ``303 or [] == 303``, and the subsequent ``len(...)`` / iteration then
    raises (``TypeError: object of type 'int' has no len()`` / ``'int' object is not iterable``) --
    crashing :func:`reconcile` / :func:`summary` / :func:`abstention_reason` and, through
    ``docmeta.add_excellence_front``, every deliverable generator. Coverage-honest: a malformed
    list-typed block reads as 'absent' (its checks skip, no count is fabricated), never a crash.
    """
    return value if isinstance(value, list) else []


# str() / repr() of a nested container recurse once per level, so a hostile upload (or any in-memory value)
# nested past the interpreter's C recursion budget raised RecursionError out of a message or a name read --
# the class _is_deep_empty was made iterative for. reprlib renders at most `maxlevel` (6) levels and bounded
# runs, so the text of a short, shallow value is unchanged and the text of a hostile one is bounded.
_BOUNDED = reprlib.Repr()
_BOUNDED.maxstring = _BOUNDED.maxother = _BOUNDED.maxlong = 80


def _shown(value: Any) -> str:
    """``repr(value)`` for a violation message, bounded in depth and length (identical for a short, shallow
    value: a band name, a count, the legacy ``0``)."""
    return _BOUNDED.repr(value)


def _text(value: Any) -> str:
    """``str(value)`` for a name read from the snapshot: a string as it is, a scalar through ``str``, a
    container through the bounded repr (``str`` of a short, shallow list IS its repr, so it reads as
    before; only a value that is never a name -- a deep or very wide container -- reads differently)."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return _BOUNDED.repr(value)
    return str(value)


def _dotted(snap: Dict[str, Any], path: str) -> Any:
    """Read a dotted snapshot path, returning None if any hop is missing/not a dict."""
    cur: Any = snap
    for hop in path.split("."):
        if not isinstance(cur, dict) or hop not in cur:
            return None
        cur = cur[hop]
    return cur


def canonical_facts(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The authoritative value for every canonical fact, read canonical-first from the snapshot.

    This is the accessor every surface SHOULD use rather than re-deriving a headline number. A
    fact whose canonical block is absent comes back as ``None`` (coverage-honest -- "not
    published" is never silently turned into 0). Counts are coerced to int; ``worst_band`` stays a
    string.
    """
    out: Dict[str, Any] = {}
    for name, (path, _concept) in CANONICAL_FACTS.items():
        raw = _dotted(snap, path)
        out[name] = raw if name == "worst_band" else _as_int(raw)
    return out


def _scored_health_rows(health: Any) -> Optional[int]:
    """How many health rows carry a usable score -- the predicate compute_executive_brief averages over
    and reconcile() verifies with (a finite, non-bool number on a row that is not 'Insufficient Data').
    None when `health` is not a list (no raw basis to count)."""
    if not isinstance(health, list):
        return None
    return sum(1 for h in health if isinstance(h, dict) and is_finite_num(h.get("score"))
               and h.get("band") != _HEALTH_BAND_NOT_SCORED)


#: Why :func:`fleet_avg_health` withholds a published average as ``unverified`` (its ``reason``).
FLEET_AVG_UNVERIFIED_REASONS: Tuple[str, ...] = ("not_a_number", "no_scored_basis")


def _count_or_none(value: Any) -> Optional[int]:
    """A published count taken only as it is: a non-negative, non-bool int, else ``None`` (never coerced)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def fleet_avg_health(snap: Any) -> Dict[str, Any]:
    """THE reader of the canonical fleet health average (G15). Every surface renders from this rather
    than re-deriving a mean or trusting a stored number blindly. Returns
    ``{state, value, n_scored, n_rows, reason}`` where ``state`` is one of:

    * ``measured``     -- ``value`` is the published, finite ``executive_brief.posture.avg_health``,
      over a scored-row basis of at least one row.
    * ``not_assessed`` -- no device was health-scored: the engine's published abstention (``None``),
      or a stored NUMBER over zero scored rows -- the pre-G15 producer's hard ``0`` (which
      :func:`reconcile` reports as a violation) is a measurement of nothing and never renders as one.
    * ``unverified``   -- a value is published but cannot be taken as a measurement; ``reason`` says why
      (:data:`FLEET_AVG_UNVERIFIED_REASONS`): ``not_a_number`` (not a finite number, a malformed upload)
      or ``no_scored_basis`` -- a finite number with NO scored-row basis at all (``health_scores`` absent
      or not a list, and no abstention record ``posture.n_scored == 0``). The engine always writes the
      ``health_scores`` list (even a failed phase's ``[]``) and publishes ``n_scored`` only on the
      abstention, only as ``0``, so that shape is never a verbatim producer output; without the rows the
      pre-G15 hard ``0`` over nothing is indistinguishable from a measurement, and :func:`reconcile` has
      nothing to verify it against. A POSITIVE ``posture.n_scored`` is no basis either: the engine never
      writes one, and a count vouching for its own average is not evidence that anything was scored.
      (Not the producer's ``posture.not_assessed`` tokens -- ``no_health_rows`` / ``all_insufficient_data``
      / ``no_scored_rows`` -- which explain an engine abstention over rows it HAD; ``reason`` is ``None``
      for ``not_assessed``, whose cause, when the engine published one, is that ``posture.not_assessed``.)
    * ``unpublished``  -- no canonical value at all (brief absent, failed ``_unavailable``, or a
      pre-posture snapshot). A consumer may fall back to its OWN mean over SCORED rows only.

    ``n_rows`` / ``n_scored`` count the ``health_scores`` list (``None`` when it is not a list; the
    producer's abstention record -- ``posture.n_scored`` equal to the integer ``0``, never a bool or a
    float -- stands in for the latter). ``value`` is ``None`` unless ``measured``; ``reason`` is ``None``
    unless ``unverified``. Total on bad input; derives only, never mutates.
    """
    s = snap if isinstance(snap, dict) else {}
    health = s.get("health_scores")
    n_rows = len(health) if isinstance(health, list) else None
    n_scored = _scored_health_rows(health)
    eb = s.get("executive_brief")
    posture = eb.get("posture") if isinstance(eb, dict) and not eb.get("_unavailable") else None
    # The producer's abstention record, taken only as it writes it: `False == 0` and `0.0 == 0` in Python.
    abstained = isinstance(posture, dict) and _count_or_none(posture.get("n_scored")) == 0
    if n_scored is None and abstained:
        n_scored = 0
    out: Dict[str, Any] = {"state": "unpublished", "value": None, "n_scored": n_scored, "n_rows": n_rows,
                           "reason": None}
    if not isinstance(posture, dict) or "avg_health" not in posture:
        return out
    value = posture.get("avg_health")
    if value is None or n_scored == 0 or abstained:
        out["state"] = "not_assessed"
    elif not is_finite_num(value):
        out.update(state="unverified", reason="not_a_number")
    elif n_scored is None:
        out.update(state="unverified", reason="no_scored_basis")
    else:
        out.update(state="measured", value=value)
    return out


_MISSING = object()
_DEEP_CONTAINERS = (dict, list, tuple, set)       # what _is_deep_empty descends into (all else is a leaf)


def _is_deep_empty(val: Any) -> bool:
    """True when `val` carries NO evidence — a falsy scalar/empty container, OR a container whose every
    element/value is itself deep-empty. This is the coverage-honesty fix for the WRAPPER-of-empties shape
    (adversarial-review finding, 2026-07-05): a section like ``{'dup_ip': [], 'dup_subnet': []}`` (a compute
    that ALWAYS returns its keys, here with zero conflicts found) is truthy, so a shallow ``not val`` check
    mislabels it 'published' — a green "seen" row for a genuinely-empty result, the exact Law-3 inversion this
    module exists to prevent. Short-circuits on the first real leaf, so a populated section stays cheap.

    Iterative (an explicit stack of iterators, depth-first in the recursive definition's order): the
    recursive form spent two interpreter frames per nesting level, so ~500 levels of an uploaded section
    raised RecursionError out of the abstention core and the census. Containers are dicts (their values)
    and lists / tuples / sets (their elements); everything else -- a frozenset included -- is a leaf judged
    by ``not leaf``. A container already on the walk is not re-entered: a shared subtree yields the same
    verdict every time, and a self-referencing one (never JSON, but reachable in memory) terminates. The memo
    HOLDS every container it entered, not just its id(): a container whose iteration builds new children
    frees each one after the walk passes it, and an id-only memo then saw a later child at the reused id,
    skipped it, and read a populated section as empty."""
    if not isinstance(val, _DEEP_CONTAINERS):
        return not val
    stack = [iter(val.values() if isinstance(val, dict) else val)]
    entered: Dict[int, Any] = {id(val): val}          # id -> the container itself, so no id can be reused
    while stack:
        for item in stack[-1]:
            if isinstance(item, _DEEP_CONTAINERS):
                if id(item) not in entered:
                    entered[id(item)] = item
                    stack.append(iter(item.values() if isinstance(item, dict) else item))
                    break                       # descend first; this level resumes where it stopped
            elif item:
                return False
        else:
            stack.pop()                         # this level is exhausted: every leaf in it was empty
    return True


def _device_not_collected(snap: Dict[str, Any], device: str) -> bool:
    """True iff `device` is in the collection blind-spot list with status 'not collected' (a fully un-collected
    device). A 'partial' device (some evidence collected) or a fully-collected one is NOT a blind spot.
    Only strings name a device (every collected host is a string): a numeric host row, or a pack's
    ``"device": 7``, raised AttributeError on ``.strip()`` and aborted assertions.evaluate_pack. A host row that
    is not a string names no device; a DEVICE that is not a string names no host the evidence can confirm was
    collected, so a fact scoped to it is a blind spot -- abstain, never a fleet-level verdict under its name."""
    if not isinstance(device, str):
        return True
    want = device.strip().lower()                        # device names vary in case (devices.json vs show-text)
    for d in _as_list(_dotted(snap, "collection_completeness.devices")):   # _as_list, NOT `or []`: a truthy non-list would crash the `for`
        host = d.get("host") if isinstance(d, dict) else None
        if isinstance(host, str) and host.strip().lower() == want:
            return _text(d.get("status", "")).strip().lower() == "not collected"
    return False


# ---------------------------------------------------------------------------------------------
# Failed analysis phases (G14). `COLLECT_PARSE_V3_23_0._run_phase` is fail-soft: a phase that raises
# returns its `_default` -- `[]` / `{}` for most sections, BYTE-IDENTICAL on disk to "computed fine,
# found nothing" -- and records its LABEL in `assessment_integrity.failed_phases`. Without reading that
# record the abstention core classified a crashed section `collected_but_empty` ("collected, nothing of
# this kind found (not a blind spot)"), and every consumer of the token inherited the lie: the census,
# the state-assertion pack (a "no Critical punch-list item" assertion PASSED over a crashed punch-list)
# and the Law-8 eval. The honest token is `analysis_unavailable`, the SAME value the engine already
# publishes for a failed protocol analysis (analyze.PROTOCOL_ASSESSABILITY_STATES).
#
# Failure records carry human phase LABELS, not snapshot keys, so attribution needs one registry. It is
# held complete against the engine source by tests/test_ssot_failed_phase_abstention.py (an AST ratchet
# over `main()`): every direct `snap_dict[key] = <result of _run_phase(label)>` edge must be registered,
# and every literal failure label must be classified. A label nobody classified -- a new phase, a
# renamed one, a malformed record -- FAILS CLOSED: it cannot be attributed, so every section whose
# value carries no evidence reads `analysis_unavailable` rather than `collected_but_empty`.
# ---------------------------------------------------------------------------------------------

ANALYSIS_UNAVAILABLE = "analysis_unavailable"

# The complete abstention codomain, in the order the census reports it.
ABSTENTION_STATES = ("published", "collected_but_empty", "not_collected", ANALYSIS_UNAVAILABLE)

# `assessment_integrity` values that mean "this block's computation failed" -- the same predicate the
# renderers' fleet-level integrity views use (html._analysis_integrity and its copies).
INTEGRITY_FAILURE_TOKENS: FrozenSet[str] = frozenset({"failed", "compute_failed", "unavailable", "error"})
# The keys :func:`audit` discloses -- and the producer (COLLECT_PARSE_V3_23_0._record_ssot_integrity_failure)
# and the webapp deliverable gate merge verbatim into `assessment_integrity`. The status key carries the
# failure token "failed", so it MUST be classified as metadata: without it `failed_sections` reported a
# reconciliation drift as a failed SECTION named `ssot_reconciliation`. audit() builds its dict from this
# tuple, so the disclosure and its classification cannot drift apart.
AUDIT_DISCLOSURE_KEYS: Tuple[str, ...] = ("ssot_reconciliation", "n_violations", "violations")
# `assessment_integrity` keys that are metadata about failures, never a section name: the per-phase failure
# record (COLLECT_PARSE_V3_23_0._record_phase_failure) plus the SSOT disclosure. Held complete against every
# literal key the producer writes by tests/test_ssot_owner_robustness.py.
_INTEGRITY_META_KEYS: FrozenSet[str] = frozenset({"failed_phases", "phase_errors", *AUDIT_DISCLOSURE_KEYS})

# Phase label -> the snapshot sections its failure leaves as a fallback. Direct `_run_phase` edges from
# `main()` (ratchet-verified), plus: compute phases whose only consumer is the embed phase that publishes
# the section; single-input derivations whose producer is the failed phase (golden drift -> feature
# compliance, protocol health -> protocol intelligence); and the labels main() records by hand around a
# multi-section try block.
PHASE_SECTIONS: Dict[str, Tuple[str, ...]] = {
    "ACL line-reachability": ("acl_line_reachability",),
    "Application intelligence": ("application_intelligence",),
    "Architecture review": ("architecture_review",),
    "BGP configured-peer baseline": ("bgp_configured_peer_baseline",),
    "Cable map": ("cable_map",),
    "Capture integrity": ("capture_integrity",),
    "Causality Chains": ("causality",),
    "Collection completeness": ("collection_completeness",),
    "Cross-Layer correlations": ("cross_layer",),
    "Data authority health": ("data_authorities",),
    "Design blueprint": ("design_blueprint", "design_nrfu", "architecture_coverage", "coverage_matrix"),
    "Detector schema": ("detector_schema",),
    "Device risk register": ("device_dossiers",),
    "Embed BGP configured-peer baseline": ("bgp_configured_peer_baseline",),
    "Embed EtherChannel operational evidence": ("etherchannel_operational_evidence",),
    "Embed FHRP configured-group baseline": ("fhrp_configured_group_baseline",),
    "Embed FHRP redundancy-domain baseline": ("fhrp_redundancy_domain_baseline",),
    "Embed IPv6 routing adjacency baseline": ("ipv6_routing_adjacency_baseline",),
    "Embed VTP extended evidence": ("vtp_extended_evidence",),
    "Embed VTP safety baseline": ("vtp_safety_baseline",),
    "Endpoint dependencies": ("endpoint_dependencies",),
    "Endpoint identity": ("endpoint_identity",),
    "EtherChannel baseline": ("etherchannel_baseline",),
    "EtherChannel operational evidence": ("etherchannel_operational_evidence",),
    "EtherChannel projection": ("etherchannel_projection",),
    "Executive brief": ("executive_brief",),
    "FHRP configured-group baseline": ("fhrp_configured_group_baseline", "fhrp_redundancy_domain_baseline"),
    "FHRP redundancy-domain baseline": ("fhrp_redundancy_domain_baseline",),
    "Failure Impact": ("failure_impact",),
    "Feature compliance": ("feature_compliance",),
    "Framework coverage": ("framework_coverage",),
    "Golden-config drift": ("golden_drift", "feature_compliance"),
    "Health Scores": ("health_scores",),
    "IPv6 routing adjacency baseline": ("ipv6_routing_adjacency_baseline",),
    "L3 Forwarding Map": ("l3_forwarding",),
    "Lifecycle risk": ("lifecycle_risk",),
    "Migration Punch-List": ("punchlist",),
    "Migration Readiness": ("migration_readiness",),
    "Migration scenarios": ("migration_scenarios",),
    "Multicast intelligence": ("multicast_intelligence",),
    "NRFU commands": ("nrfu_commands",),
    "Operational drift": ("operational_drift",),
    "Physical Health": ("physical_health",),
    "Platform health": ("platform_health",),
    "Protocol Health": ("protocol_health", "protocol_intelligence"),
    "Protocol assessability": ("protocol_assessability",),
    "Protocol intelligence": ("protocol_intelligence",),
    "QoS audit": ("qos_audit",),
    "Remediation plan": ("remediation_plan",),
    "STP topology baseline": ("stp_topology_baseline",),
    "Schema census / fact lineage": ("schema_census", "fact_lineage"),
    "Score Calibration": ("calibration",),
    "Score Sensitivity": ("score_sensitivity",),
    "Segmentation audit": ("segmentation",),
    "Service map": ("service_map",),
    "Software risk screening": ("software_risk",),
    "State assertion pack": ("state_assertions",),
    "Subnet intelligence": ("subnet_intelligence",),
    "Syslog intelligence": ("syslog_intelligence",),
    "Traffic assurance": ("traffic_assurance",),
    "Traffic evidence custody": ("traffic_evidence_custody",),
    "Unknown evidence": ("unknown_evidence",),
    "VLAN cutover matrix": ("vlan_cutover",),
    "VTP extended evidence": ("vtp_extended_evidence",),
    "VTP safety baseline": ("vtp_safety_baseline",),
    "Validation plan": ("validation_plan",),
    "Zero-egress attestation": ("attestation",),
    "move groups": ("move_groups", "wave_sequencing"),
}

# Intermediate computations that publish no section of their own but feed several: a failure cannot be
# attributed to one section, so it fails closed exactly like an unknown label (named here only so the
# ratchet can tell a CLASSIFIED intermediate from a label nobody looked at).
INTERMEDIATE_PHASES: FrozenSet[str] = frozenset({
    "Flow paths", "IPv6 routing subject scope", "PTP readiness", "Trunk-capture gaps",
    "VTP safety subject scope", "data quality", "dependency map", "reconcile CDP split-node names",
})

# Failures that leave no analysis section as a fallback: workbook/document writers, redaction passes,
# custody / manifest / receipt finalization, registry-authority health (reported faithfully inside
# `data_authorities` itself) and post-assembly self-checks. Their integrity is disclosed through
# `assessment_integrity` and the run custody, not through a section's abstention.
NON_SECTION_PHASES: FrozenSet[str] = frozenset({
    # redaction passes
    "redact collected dataclasses", "redact workbook cells", "Raw capture redaction",
    # artifact emission (_emit_artifact) and receipt refresh (_atomic_receipt_refresh)
    "Topology diagrams", "Phase timings", "HTML Explorer", "Runbook DOCX", "Executive deck PPTX",
    "CRD DOCX", "Engagement workflow DOCX", "Architecture review DOCX", "Operations handbook DOCX",
    "Design document DOCX", "MOP DOCX", "Assessment snapshot", "Assessment workbook",
    "Assessment workbook BOUND receipt", "HTML Explorer BOUND receipt", "Runbook DOCX BOUND receipt",
    "MOP DOCX BOUND receipt",
    # mandatory producer-boundary steps (_record_mandatory_failure)
    "Input custody", "Raw evidence custody", "Post-redaction evidence custody",
    "Raw capture redaction verification", "Shareable redaction verification", "Run manifest",
    "Protocol Assurance source authority", "Protocol Assurance pre-manifest authority",
    "Protocol Assurance complete export", "Incomplete marker", "Incomplete marker clearance",
    # per-registry data authority (the data_authorities section records each one's health itself)
    "OUI registry authority", "Port registry authority", "EoL knowledge-base authority",
    # post-assembly self-checks
    "SSOT self-check", "Gate closing summary",
})
_NON_SECTION_SUFFIXES = (" sheet",)                 # workbook sheet writers: their return value is unused
_NON_SECTION_PREFIXES = ("interface rows (",)       # per-host workbook row writers (f-string labels)


def phase_classification(label: Any) -> str:
    """Classify one failure label: ``sections`` (attributed through :data:`PHASE_SECTIONS`),
    ``intermediate`` (feeds several sections -> fails closed), ``non_section`` (leaves no section
    fallback) or ``unknown`` (nobody classified it -> fails closed). Every classified label is a string, so
    anything else is ``unknown`` without being rendered: ``str()`` of a hostile nesting raised RecursionError
    out of :func:`failed_sections`, and no ``str()`` of a JSON number, list or object spells a label."""
    if not isinstance(label, str):
        return "unknown"
    lab = label
    if lab in PHASE_SECTIONS:
        return "sections"
    if lab in INTERMEDIATE_PHASES:
        return "intermediate"
    if lab in NON_SECTION_PHASES or lab.endswith(_NON_SECTION_SUFFIXES) or lab.startswith(_NON_SECTION_PREFIXES):
        return "non_section"
    return "unknown"


def failed_sections(snap: Any) -> Tuple[FrozenSet[str], bool]:
    """Which snapshot sections are a failed phase's fallback -> ``(direct, unattributed)``.

    ``direct`` is every top-level section attributable to a failure: a ``failed_phases`` label's
    :data:`PHASE_SECTIONS` entry, an ``assessment_integrity[<section>]`` stamped with a failure token
    (``executive_brief: compute_failed``), and a top-level ``{"_unavailable": true}`` sentinel.
    ``unattributed`` is True when some failure cannot be pinned to sections -- an intermediate or
    unknown label, or a ``failed_phases`` record that is not a list (the malformed-record rule the
    webapp integrity summary applies). Total on bad input; derives only, never mutates.
    """
    s = snap if isinstance(snap, dict) else {}
    direct: set = set()
    unattributed = False
    integrity = s.get("assessment_integrity")
    if isinstance(integrity, dict):
        raw = integrity.get("failed_phases")
        if isinstance(raw, list):
            for label in raw:
                kind = phase_classification(label)
                if kind == "sections":
                    direct.update(PHASE_SECTIONS[label])        # "sections" is only ever a string label
                elif kind != "non_section":
                    unattributed = True
        elif raw:
            unattributed = True
        for key, value in integrity.items():
            if (isinstance(key, str) and key not in _INTEGRITY_META_KEYS
                    and isinstance(value, str) and value.strip().lower() in INTEGRITY_FAILURE_TOKENS):
                direct.add(key)
    for key, value in s.items():
        if isinstance(value, dict) and value.get("_unavailable"):
            direct.add(key)
    return frozenset(direct), unattributed


# One hop downstream (G14). A headline fact stored under `executive_brief` is DERIVED from other
# sections: with the 'Health Scores' phase failed, `compute_executive_brief` still publishes counts taken
# over the `[]` fallback, and the abstention core -- which looked only at the fact path's own top-level
# section -- classified them `collected_but_empty` ("looked, found nothing"); a user assertion
# `executive_brief.posture.n_critical == 0` PASSED over the crash. Keyed by dotted-path prefix (the
# longest registered prefix wins); the value is the raw-basis sections the fact is computed from. Held
# complete for every CANONICAL_FACTS path under `executive_brief` by
# tests/test_ssot_failed_phase_abstention.py, which also cross-checks each `== len(<section>)` basis
# hint in CANONICAL_FACTS. Facts outside `executive_brief` (lifecycle_risk.summary.*,
# design_blueprint.summary.*) are derived inside their own section, whose failure is already `direct`.
DERIVED_FACT_BASIS: Dict[str, Tuple[str, ...]] = {
    "executive_brief.posture": ("health_scores",),
    "executive_brief.scale.n_devices": ("health_scores",),
    "executive_brief.scale.n_collected": ("collection_completeness",),
    "executive_brief.scale.n_endpoints": ("endpoint_identity",),
    "executive_brief.scale.n_domains": ("application_intelligence",),
    # vlan_inventory(interfaces, l3_forwarding, service_map): the two computed inputs can fail
    "executive_brief.scale.n_vlans": ("l3_forwarding", "service_map"),
}


_POSTURE = "executive_brief.posture"     # the health-row aggregates (DERIVED_FACT_BASIS: health_scores)


def _is_posture_path(path: Any) -> bool:
    return isinstance(path, str) and (path == _POSTURE or path.startswith(_POSTURE + "."))


def _posture_unbacked(snap: Dict[str, Any]) -> bool:
    """True when the snapshot carries no ``health_scores`` LIST: the posture facts aggregate over rows it
    does not have (:func:`fleet_avg_health`'s ``no_scored_basis``). The engine always writes the list."""
    return not isinstance(snap.get("health_scores"), list)


def fact_basis(path: Any) -> Tuple[str, ...]:
    """The snapshot sections a (dotted) fact path is computed from: its own top-level section first,
    then the raw basis of the longest :data:`DERIVED_FACT_BASIS` prefix that covers it. ``()`` for a
    non-string / empty path. Total; derives only."""
    if not isinstance(path, str) or not path:
        return ()
    best = ""
    for prefix in DERIVED_FACT_BASIS:
        if (path == prefix or path.startswith(prefix + ".")) and len(prefix) > len(best):
            best = prefix
    top = path.split(".", 1)[0]
    return (top,) + tuple(s for s in DERIVED_FACT_BASIS.get(best, ()) if s != top)


def _abstention(snap: Dict[str, Any], subject: Any, device: Optional[str],
                failures: Tuple[FrozenSet[str], bool]) -> str:
    """:func:`abstention_reason` with the snapshot's :func:`failed_sections` computed once by the caller."""
    # A fact about an UN-collected device is a blind spot, regardless of the fleet-level value.
    if device and _device_not_collected(snap, device):
        return "not_collected"
    direct, unattributed = failures
    # The section IS a failed phase's fallback, or the fact is DERIVED from one: whatever it holds ([] /
    # {} / an error-state default / an _unavailable sentinel / a count over the fallback / nothing at
    # all) is not evidence. Checked before presence, so an ABSENT section of a failed phase is not
    # mislabelled a collection blind spot either.
    if any(section in direct for section in fact_basis(subject)):
        return ANALYSIS_UNAVAILABLE
    # The posture facts are aggregates over the health rows, and fleet_avg_health withholds them when the
    # snapshot carries no health_scores LIST (no_scored_basis). The same absence is a blind spot here: the
    # core read an unbacked average as `published` and a stripped zero as `collected_but_empty` ("looked,
    # found nothing"), so a user assertion `n_critical == 0` PASSED over no health evidence at all. The
    # engine always writes the list (a failed phase's `[]` is attributed above), so its output is unchanged.
    if _is_posture_path(subject) and _posture_unbacked(snap):
        return "not_collected"
    if isinstance(subject, str) and "." in subject:
        val = _dotted(snap, subject)
    else:
        try:
            val = snap.get(subject, _MISSING)
        except TypeError:            # an unhashable subject (a list from a malformed pack) names no section
            val = _MISSING
    if val is _MISSING or val is None:
        return "not_collected"
    # DEEP-empty, not just shallow-falsy: a wrapper whose every payload is empty (a compute that always
    # returns its keys but found nothing) is 'collected_but_empty', never the green 'published' -- unless a
    # failure that could not be attributed means this empty may itself be a crashed phase's fallback.
    if _is_deep_empty(val):
        return ANALYSIS_UNAVAILABLE if unattributed else "collected_but_empty"
    return "published"


def abstention_reason(snap: Dict[str, Any], subject: str, device: str = None) -> str:
    """Why is `subject` absent — the coverage-honest core made callable. `subject` is a top-level snapshot
    section key (e.g. 'fhrp', 'vpc') or a dotted path (e.g. 'executive_brief.scale.n_vlans'); `device` optionally
    scopes the question to one host. Returns exactly one of :data:`ABSTENTION_STATES`:
      'published'            -- present and non-empty (a real result)
      'collected_but_empty'  -- present but empty/zero (collected; genuinely nothing of this kind found)
      'not_collected'        -- the axis is absent, OR (device given) that device was never collected -- a BLIND
                                SPOT, never a clean result. This is the 'not observed never becomes healthy' rule
                                (the bare show-logging-on-NX-OS false-health class) made into a first-class token.
      'analysis_unavailable' -- the section's analysis phase FAILED this run (see :func:`failed_sections`), or
                                the fact is derived from a section that did (see :data:`DERIVED_FACT_BASIS`),
                                so whatever it holds is a fallback: neither a blind spot of collection nor a
                                finding that nothing is there.
    Pure presence/absence logic over the snapshot -- no model, no egress; total (safe on None / bad input)."""
    snap = snap if isinstance(snap, dict) else {}
    return _abstention(snap, subject, device, failed_sections(snap))


# ---------------------------------------------------------------------------------------------
# schema census (J3): a snapshot self-describes what it actually SAW -- the SuzieQ `describe`
# analog. For EVERY top-level snapshot section, project the coverage-honest abstention token onto a
# queryable coverage map, so an access-only collection (e.g. the Meridian reference fleet, where a whole
# distribution/core tier is UN-collected) reports exactly what was seen vs what is a blind spot,
# instead of a rendered "filler" output whose real cause is an uncollected tier, not a code bug.
# ---------------------------------------------------------------------------------------------

SCHEMA_CENSUS_SCHEMA = "schema_census/1"

# The honest note per abstention token. Never "ok"/"healthy": absence of evidence is never health.
_CENSUS_NOTE = {
    "published":           "seen — collected and non-empty",
    "collected_but_empty": "collected, nothing of this kind found (not a blind spot)",
    "not_collected":       "blind spot — not collected",
    ANALYSIS_UNAVAILABLE:  "analysis failed this run — empty/absent is not evidence of absence "
                           "(see assessment_integrity.failed_phases)",
}


def _census_kind(val: Any) -> str:
    """The shape of a section, for the census `kind` column: absent / list / dict / scalar.
    Purely structural (no model, no dates) so the census stays deterministic across runs."""
    if val is None:
        return "absent"
    if isinstance(val, list):
        return "list"
    if isinstance(val, dict):
        return "dict"
    return "scalar"


def compute_schema_census(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The per-section coverage census -- a snapshot's self-description of what it actually saw.

    For EVERY top-level snapshot section key, emit one row::

        {key, state, count, kind, note}

    where ``state`` is the coverage-honest token :func:`abstention_reason` returns
    (``published`` / ``collected_but_empty`` / ``not_collected`` / ``analysis_unavailable``),
    ``count`` is ``len()`` when the section is a list or dict (else ``None`` -- a scalar/absent
    section has no cardinality), ``kind`` is the section's structural shape, and ``note`` is a short
    honest phrase. A present-but-empty section is ``collected_but_empty`` (collected, genuinely
    nothing found -- NOT a blind spot); an absent section is ``not_collected`` (a real blind spot);
    a failed phase's fallback is ``analysis_unavailable``. Nothing is ever labelled "ok"/"healthy":
    absence of evidence is never health (Law 3).

    ``summary.n_analysis_unavailable`` is emitted only when it is non-zero, so a clean run's summary
    keeps exactly its four historical keys (the golden snapshot and ``schema_census/1`` stay stable);
    the counters always partition ``n_sections``.

    Deterministic (presence/absence only -- no dates, no model) and total on bad input: a non-dict
    snapshot yields an empty-but-well-formed census rather than raising.
    """
    snap = snap if isinstance(snap, dict) else {}
    failures = failed_sections(snap)
    sections: List[Dict[str, Any]] = []
    n_pub = n_empty = n_absent = n_unavailable = 0
    for key in snap:                                   # iterate a snapshot copy's keys (see caller)
        val = snap.get(key)
        state = _abstention(snap, key, None, failures)
        if state == "published":
            n_pub += 1
        elif state == "collected_but_empty":
            n_empty += 1
        elif state == ANALYSIS_UNAVAILABLE:
            n_unavailable += 1
        else:
            n_absent += 1
        count = len(val) if isinstance(val, (list, dict)) else None
        sections.append({
            "key": key,
            "state": state,
            "count": count,
            "kind": _census_kind(val),
            "note": _CENSUS_NOTE.get(state, _CENSUS_NOTE["not_collected"]),
        })
    summary_block: Dict[str, int] = {
        "n_published": n_pub,
        "n_collected_but_empty": n_empty,
        "n_not_collected": n_absent,
    }
    if n_unavailable:
        summary_block["n_analysis_unavailable"] = n_unavailable
    summary_block["n_sections"] = len(sections)
    return {
        "schema": SCHEMA_CENSUS_SCHEMA,
        "sections": sections,
        "summary": summary_block,
    }


# ---------------------------------------------------------------------------------------------
# fact lineage (J2): attribute-level provenance for the canonical headline facts (Infrahub-style).
# For each CANONICAL_FACTS entry, name WHERE the number comes from: its dotted canonical path, the
# published value, the coverage-honest state of that path, and the one-line basis/derivation
# already recorded in CANONICAL_FACTS -- provenance made queryable by REUSING the SSOT contract,
# not a parallel one. (source_command depth -- mapping each fact to the exact show-command -- is
# DEFERRED; the basis string is the v1 provenance.)
# ---------------------------------------------------------------------------------------------

FACT_LINEAGE_SCHEMA = "fact_lineage/1"


def compute_fact_lineage(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Attribute-level provenance for every canonical headline fact.

    Emits one row per :data:`CANONICAL_FACTS` entry::

        {name, value, path, state, basis}

    where ``path`` is the dotted canonical snapshot path, ``value`` is the authoritative value from
    :func:`canonical_facts` (read canonical-first; ``None`` when the block isn't published),
    ``state`` is :func:`abstention_reason` on that path (``published`` / ``collected_but_empty`` /
    ``not_collected`` / ``analysis_unavailable`` -- so an un-published block reads as a blind spot,
    and a block whose phase failed reads as unavailable, never a silent 0), and
    ``basis`` is the one-line concept/derivation named in ``CANONICAL_FACTS`` (the "== len(...)"
    hints), so a reader sees WHERE each headline number comes from. Reuses the SSOT contract rather
    than inventing a parallel provenance store. Total on bad input.
    """
    snap = snap if isinstance(snap, dict) else {}
    values = canonical_facts(snap)
    failures = failed_sections(snap)
    facts: List[Dict[str, Any]] = []
    for name, (path, concept) in CANONICAL_FACTS.items():
        facts.append({
            "name": name,
            "value": values.get(name),
            "path": path,
            "state": _abstention(snap, path, None, failures),
            "basis": concept,
        })
    return {"schema": FACT_LINEAGE_SCHEMA, "facts": facts}


# ---------------------------------------------------------------------------------------------
# Segmentation posture (Law 1 accessor). The L3 gateway tier's segmentation facts have ONE owner --
# ``analyze.compute_segmentation`` -> ``snap['segmentation']`` -- but three deliverables
# (design/crd/archreview) each re-derived their own from ``snap['interfaces']`` and asked a
# *different* question while using the owner's label: they counted every non-default VRF configured
# ANYWHERE (mgmt0's management VRF, a vPC keepalive VRF) as a "VRF in use", where the owner counts
# only the VRF buckets that actually CARRY a gateway SVI. On the Meridian reference fleet that reads 4 vs 1 for the
# same phrase, in the same deliverable set, off the same snapshot -- and it flipped archreview's
# SEC-2 gate off the owner's `flat` verdict. This accessor is the one place both questions are
# answered, each under its own name.
# ---------------------------------------------------------------------------------------------

def _is_svi_port(name: Any) -> bool:
    """True for an SVI port name -- the owner's own predicate, ``^Vlan\\d+$`` (case-insensitive),
    expressed without a regex so this module stays dependency-light."""
    s = str(name or "")
    return s[:4].lower() == "vlan" and s[4:].isdigit()


# The names that are NOT a separate routing table: the device's own default/global VRF, plus
# '(global)' -- the synthetic bucket label analyze.compute_segmentation gives the unsegmented
# gateways in `segmentation.vrfs`. Reading that label as a real VRF would turn a flat fabric into a
# 1-VRF "segmented" one at the first read of the owner's own block.
_GLOBAL_VRF_NAMES = ("default", "global", "(global)")


def _is_nondefault_vrf(vrf: str) -> bool:
    """A VRF name that actually separates a routing table (the shared default/global names are not)."""
    return bool(vrf) and vrf.lower() not in _GLOBAL_VRF_NAMES


def segmentation_facts(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The L3 segmentation posture, read from its one owner (``snap['segmentation']``).

    Returns ``{n_gateways, n_with_acl, coverage_pct, n_gateway_vrfs, gateway_vrfs, other_vrfs,
    flat, source}``:

    * ``n_gateways`` / ``n_with_acl`` / ``coverage_pct`` -- the gateway-SVI ACL posture
      (``segmentation.gateway_acl``).
    * ``n_gateway_vrfs`` -- how many VRF *buckets* carry a gateway SVI, counting the global table as
      one (``segmentation.summary.n_vrfs``). This is NOT "how many VRFs are configured".
    * ``gateway_vrfs`` -- the NON-global VRF names among those; empty on a flat fabric. This is the
      figure a segmentation claim must be graded on.
    * ``other_vrfs`` -- non-default VRFs configured somewhere on the fleet that carry NO gateway SVI
      (management / keepalive VRFs). A DIFFERENT fact, named separately: they segment no user
      traffic, so counting them as "VRFs in use" reads a flat fabric as partially segmented.
    * ``flat`` -- the owner's verdict: gateways exist, none in a non-global VRF, none with an ACL.

    Coverage-honest: with ``snap['segmentation']`` absent the gateway figures are DERIVED from
    ``snap['interfaces']`` using the owner's own predicate and ``source`` reads ``derived``; with
    neither available the counts are ``None`` (never a fabricated 0) and ``flat`` is ``None``.
    ``other_vrfs`` is always interface-derived -- the owner publishes no such list. Total on bad
    input; derives only, never mutates.
    """
    snap = snap if isinstance(snap, dict) else {}
    seg = _as_dict(snap.get("segmentation"))
    ssum = _as_dict(seg.get("summary"))
    gacl = _as_dict(seg.get("gateway_acl"))

    # One pass over the interfaces: every non-default VRF seen anywhere, plus the gateway-scoped
    # derivation (the fallback, and the source of `other_vrfs` in every case).
    all_vrfs: set = set()
    gw_buckets: set = set()
    n_gw_derived = n_acl_derived = 0
    # _text, not str(): str() of a hostile nesting raised RecursionError; a shallow value reads as before.
    for _host, ports in _as_dict(snap.get("interfaces")).items():
        for pname, pdet in _as_dict(ports).items():
            pdet = _as_dict(pdet)
            vrf = _text(pdet.get("vrf") or "").strip()
            nondefault = _is_nondefault_vrf(vrf)
            if nondefault:
                all_vrfs.add(vrf)
            if _is_svi_port(pname) and _text(pdet.get("svi_ip") or "").strip():
                n_gw_derived += 1
                gw_buckets.add(vrf if nondefault else "(global)")
                if _text(pdet.get("acl_in") or "").strip() or _text(pdet.get("acl_out") or "").strip():
                    n_acl_derived += 1

    published = _as_int(gacl.get("n_gateways"))
    if published is None:
        published = _as_int(ssum.get("n_gateways"))
    from_owner = published is not None
    source = "segmentation" if from_owner else ("derived" if n_gw_derived else "unavailable")

    if from_owner:
        n_gateways = published
        n_with_acl = _as_int(gacl.get("n_with_acl"))
        n_gateway_vrfs = _as_int(ssum.get("n_vrfs"))
        # the owner's per-VRF gateway census; '(global)' is the unsegmented bucket, never a real VRF
        gateway_vrfs = sorted({_text(r.get("vrf")) for r in _as_list(seg.get("vrfs"))
                               if isinstance(r, dict) and _is_nondefault_vrf(_text(r.get("vrf") or "").strip())})
        if not _as_list(seg.get("vrfs")):
            gateway_vrfs = sorted(b for b in gw_buckets if b != "(global)")
    else:
        n_gateways = n_gw_derived or None
        n_with_acl = n_acl_derived if n_gw_derived else None
        n_gateway_vrfs = len(gw_buckets) or None
        gateway_vrfs = sorted(b for b in gw_buckets if b != "(global)")

    pct = gacl.get("coverage_pct") if from_owner else None
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        pct = (round(100.0 * n_with_acl / n_gateways, 1)
               if (n_gateways and isinstance(n_with_acl, int)) else None)
    if not n_gateways:
        # G15 class: a share over ZERO gateways is not a percentage (the owner publishes 0.0 there).
        pct = None

    flat = ssum.get("flat")
    if not isinstance(flat, bool):
        flat = (bool(n_gateways) and not gateway_vrfs and n_with_acl == 0) if n_gateways else None

    return {"n_gateways": n_gateways, "n_with_acl": n_with_acl, "coverage_pct": pct,
            "n_gateway_vrfs": n_gateway_vrfs, "gateway_vrfs": gateway_vrfs,
            "other_vrfs": sorted(all_vrfs - set(gateway_vrfs)), "flat": flat, "source": source}


def _rounded_mean(scored: List[Any]) -> int:
    """``round(mean(scored))`` exactly as compute_executive_brief computes it (a float sum), falling back to
    the EXACT rational mean only when that float arithmetic overflows. Every score is finite
    (``is_finite_num``), but two of them near the float maximum -- 1.7e308 is a plain JSON number -- summed to
    ``inf`` and ``round(inf)`` raised OverflowError, and an int too large for a float beside a float raised it
    from the sum itself: out of reconcile / summary / audit and, through docmeta.add_excellence_front, every
    DOCX. The engine never scores outside 0..100, so the normal path (and its half-way rounding) is untouched."""
    try:
        mean = sum(scored) / len(scored)
    except OverflowError:
        mean = math.inf
    if math.isfinite(mean):
        return round(mean)
    return round(sum(Fraction(x) for x in scored) / len(scored))


def reconcile(snap: Dict[str, Any], _ran: Optional[List[str]] = None) -> List[str]:
    """Return human-readable SSOT violations: a published canonical value that disagrees with an
    independent derivation from the raw evidence. Empty list == every published fact reconciles.

    Coverage-honest: a canonical block that isn't published yet (e.g. a partially-assembled or
    minimal snapshot whose ``executive_brief.scale`` is ``None``) is SKIPPED, not flagged -- the
    guard fires only when both the published value AND its raw basis are present, so it never
    invents a violation from absent evidence.

    That skipping is why an empty return is NOT by itself a pass. Every check here is gated on its
    raw basis being present, so a snapshot that publishes all the canonical blocks but carries none
    of the raw arrays reconciles NOTHING and returns ``[]`` -- indistinguishable, from the return
    value alone, from a snapshot that reconciled everything. ``_ran`` is the out-parameter that
    closes that: pass a list and it receives the name of every check that ACTUALLY executed, so a
    caller can tell "verified, all clean" from "verified nothing". :func:`summary` uses it; nothing
    else needs to, which is why it stays private rather than changing the return type.

    Total on bad input: a snapshot that is not a dict reconciles nothing, and a malformed value is
    reported (bounded) or skipped, never raised on.
    """
    snap = snap if isinstance(snap, dict) else {}
    violations: List[str] = []
    # Every published summary block is coerced via _as_dict, NOT `_dotted(...) or {}`: `or {}` keeps a
    # TRUTHY non-dict (a str/list from a poisoned or hand-edited --no-collect snapshot), and the many
    # `.get` calls below would then raise AttributeError -- crashing this guard (and, via
    # docmeta.add_excellence_front -> ssot.summary, every deliverable generator). See _as_dict.
    # The list-typed bindings below are the exact TWIN of that class and use _as_list for the SAME
    # reason, NOT `... or []`: `or []` keeps a truthy non-list (an int/str/dict/bool), and the
    # subsequent len()/iteration then raises (`len(303)` / `for d in 303`). See _as_list.
    scale = _as_dict(_dotted(snap, "executive_brief.scale"))
    posture = _as_dict(_dotted(snap, "executive_brief.posture"))
    cc = _as_dict(_dotted(snap, "collection_completeness.summary"))
    lc = _as_dict(_dotted(snap, "lifecycle_risk.summary"))
    per_device = _as_list(_dotted(snap, "lifecycle_risk.per_device"))
    health = _as_list(snap.get("health_scores"))
    endpoints = _as_list(snap.get("endpoint_identity"))

    def check(name: str, published: Any, derived: Any, basis: str) -> None:
        pi, di = _as_int(published), _as_int(derived)
        if pi is None or di is None:
            return  # not both present -> coverage-honest skip (and NOT counted as a check that ran)
        if _ran is not None:
            _ran.append(name)
        if pi != di:
            violations.append(f"{name}={pi} but {basis}={di}")

    # --- scale -------------------------------------------------------------------------------
    if "n_devices" in scale and health:
        check("executive_brief.scale.n_devices", scale.get("n_devices"), len(health), "len(health_scores)")
    if "n_devices" in scale and "inventory" in cc:
        check("executive_brief.scale.n_devices", scale.get("n_devices"), cc.get("inventory"),
              "collection_completeness.summary.inventory")
    if "n_collected" in scale and "complete" in cc:
        check("executive_brief.scale.n_collected", scale.get("n_collected"), cc.get("complete"),
              "collection_completeness.summary.complete")
    # ...and against an INDEPENDENT raw basis, not just the producer-shared sibling summary.complete: the device
    # list carries ONLY the blind spots ('the report lists only the blind spots', analyze.py), so collected =
    # inventory - len(devices). Without this, a coordinated off-by-N drift writing the SAME wrong value to both
    # scale.n_collected and summary.complete passes -- 'blind' silently reads 'fully collected' (audit-4 #11).
    _cc_devices = _dotted(snap, "collection_completeness.devices")
    _inv = _as_int(cc.get("inventory"))
    if "n_collected" in scale and _inv is not None and isinstance(_cc_devices, list):
        check("executive_brief.scale.n_collected", scale.get("n_collected"), _inv - len(_cc_devices),
              "collection_completeness.summary.inventory - len(collection_completeness.devices)")
    if "n_endpoints" in scale and endpoints:
        check("executive_brief.scale.n_endpoints", scale.get("n_endpoints"), len(endpoints),
              "len(endpoint_identity)")
    # n_domains (the broadcast/management application domains) was published + served via SSOT but had NO
    # reconcile check -- a drift vs its raw basis went undetected. It MUST equal len(application_intelligence
    # .domains), the source compute_application_intelligence counts it from (audit-5 scale-ssot #1/#2).
    _ai_domains = _dotted(snap, "application_intelligence.domains")
    if "n_domains" in scale and isinstance(_ai_domains, list) and _ai_domains:
        check("executive_brief.scale.n_domains", scale.get("n_domains"), len(_ai_domains),
              "len(application_intelligence.domains)")
    if "n_vlans" in scale:
        try:  # vlan_inventory is the canonical VLAN-in-use derivation; import lazily (avoids cycles)
            from cisco_toolkit.analyze import vlan_inventory
            derived_vlans = len(vlan_inventory(snap))
            if derived_vlans:   # raw-evidence guard (like the n_devices/n_endpoints checks): a slimmed snapshot
                # publishes n_vlans but strips the raw VLAN arrays -> derives 0 -> SKIP, never a false violation.
                check("executive_brief.scale.n_vlans", scale.get("n_vlans"), derived_vlans,
                      "len(vlan_inventory)")
        except Exception:
            pass  # not derivable on this snapshot shape -> skip, never a false violation

    # --- posture (health bands) --------------------------------------------------------------
    # The raw basis is a health_scores LIST -- unless the 'Health Scores' phase FAILED (or a failure
    # that cannot be attributed sits beside an EMPTY list): that list is then the phase's `[]` fallback,
    # and a check against it certified the posture -- `summary()` reported `verified: True` over a
    # crashed phase. Such a basis verifies nothing, and nothing is counted as having run.
    _failed_direct, _failed_unattributed = failed_sections(snap)
    _health_basis = (isinstance(snap.get("health_scores"), list)
                     and "health_scores" not in _failed_direct
                     and not (_failed_unattributed and not health))
    # is_finite_num, not `isinstance(...) and math.isfinite(...)`: that idiom rejects the JSON
    # Infinity/NaN correctly but CRASHES on the other value json.loads accepts -- an integer
    # literal of unbounded precision, on which math.isfinite() itself raises OverflowError
    # before it can return False. reconcile() runs inside docmeta.add_excellence_front, so
    # that aborted EVERY deliverable in the docx family over one health score.
    scored = [h.get("score") for h in health
              if isinstance(h, dict) and is_finite_num(h.get("score"))
              and h.get("band") != _HEALTH_BAND_NOT_SCORED]
    # A row whose band is outside the producer's vocabulary (a list / dict / number / unknown text -- never an
    # engine output) or that is not a record at all could be ANY band. The counts below compare with ==, so
    # such a row silently counted as "not Critical": `n_critical: 0` beside a row banded ["Critical"] was
    # certified, and summary() said `verified: True` over rows nobody could read -- absence of a readable
    # band rendered as health. A band fact that row could change is reported as unverifiable instead.
    unreadable = sum(1 for h in health if not (isinstance(h, dict) and isinstance(h.get("band"), str)
                                               and h["band"] in _HEALTH_BAND_VOCABULARY))
    _unreadable_note = f"{unreadable} health row(s) carry no recognised band"
    if _health_basis and health:
        for field, band in (("n_critical", _HEALTH_BAND_CRITICAL), ("n_poor", _HEALTH_BAND_POOR)):
            if field not in posture:
                continue
            path = f"executive_brief.posture.{field}"
            cnt = sum(1 for h in health if isinstance(h, dict) and h.get("band") == band)
            published = posture.get(field)
            pi = _as_int(published)
            if published is not None and pi is None:
                continue                # not a count: the coverage-honest skip check() applies
            if unreadable and (cnt <= pi <= cnt + unreadable if pi is not None else not (cnt or scored)):
                # consistent with SOME reading of the unreadable rows, so neither confirmed nor refuted (a
                # value outside that range is refuted below exactly as before)
                if _ran is not None:
                    _ran.append(path)
                violations.append(f"{path}={pi} but {_unreadable_note}, so "
                                  f"count(health_scores.band=={band}) cannot be verified")
                continue
            if published is not None:
                check(path, published, cnt, f"count(health_scores.band=={band})")
                continue
            # G15: a None band count is the producer's abstention for a fleet with NOTHING scored and
            # no such band observed -- verified in both directions, exactly like avg_health below.
            if _ran is not None:
                _ran.append(path)
            if cnt:
                violations.append(f"{path}=None (not assessed) but {cnt} health row(s) carry the {band} band")
            elif scored:
                violations.append(f"{path}=None (not assessed) but {len(scored)} health row(s) are scored")
    # avg_health and worst_band are DERIVED aggregates published in posture; both are counted as
    # self-verified facts, so both must be reconciled too (mirroring compute_executive_brief
    # exactly -> no tolerance, no false positives). The mean excludes "Insufficient Data" scores.
    # G15: verified in BOTH directions. With zero scored rows the only honest value is the abstention
    # (None): a published number there -- the pre-G15 producer's hard 0, carried by every snapshot it
    # wrote -- is a measurement of nothing. With scored rows, a published None withholds a real mean.
    # The raw basis is a health_scores LIST (an empty one included: zero rows is zero scored rows).
    if _health_basis and "avg_health" in posture:
        published_avg = posture.get("avg_health")
        if scored and published_avg is not None:
            check("executive_brief.posture.avg_health", published_avg,
                  _rounded_mean(scored), "round(mean(scored health_scores.score))")
        else:
            if _ran is not None:
                _ran.append("executive_brief.posture.avg_health")
            if scored:
                violations.append(
                    f"executive_brief.posture.avg_health=None (not assessed) but {len(scored)} "
                    f"health row(s) are scored")
            elif published_avg is not None:
                violations.append(   # _shown: a bounded repr (repr() of a hostile nesting raised)
                    f"executive_brief.posture.avg_health={_shown(published_avg)} but 0 of {len(health)} "
                    f"health row(s) are scored (a number published for nothing; expected None)")
    if _health_basis and health:
        if "worst_band" in posture:
            # Only a string can be a band of the vocabulary, so only strings are collected: a list / dict
            # band (a malformed or uploaded snapshot) is unhashable and raised TypeError here -- through
            # summary() that aborted docmeta.add_excellence_front, i.e. every DOCX. Like "Unrecognised" or 7
            # it is an unreadable band (counted in `unreadable` above), never read as the band it contains.
            bands_present = {h["band"] for h in health if isinstance(h, dict) and isinstance(h.get("band"), str)}
            derived_worst = next((b for b in _HEALTH_BAND_ORDER if b in bands_present), "")
            published_worst = posture.get("worst_band")
            if unreadable and derived_worst != _HEALTH_BAND_ORDER[0]:
                # an unreadable row could be worse than every band observed; only an observed Critical row
                # (nothing is worse) still decides the most-severe band
                violations.append(
                    f"executive_brief.posture.worst_band={_shown(published_worst)} but {_unreadable_note}, "
                    f"so the most-severe band present cannot be determined")
            elif derived_worst and published_worst != derived_worst:
                # a wrong band, OR (G15) a band withheld (None / "") while one is observed
                violations.append(
                    f"executive_brief.posture.worst_band={_shown(published_worst)} but "
                    f"most-severe band present={derived_worst!r}")

    # --- lifecycle bands (per_device is the raw basis) ---------------------------------------
    if per_device:
        # the lifecycle summary republishes the device count (consumed as the EoL rollup total in analyze.py); it
        # must reconcile to the raw per_device length, else a lifecycle device-count drift diverges silently from
        # the SSOT device count (audit-4 #12).
        if "n_devices" in lc:
            check("lifecycle_risk.summary.n_devices", lc.get("n_devices"), len(per_device),
                  "len(lifecycle_risk.per_device)")
        for field, band in _LIFECYCLE_BANDS.items():
            if field in lc:
                cnt = sum(1 for d in per_device if isinstance(d, dict) and d.get("band") == band)
                check(f"lifecycle_risk.summary.{field}", lc.get(field), cnt,
                      f"count(per_device.band=={band})")
        by_band = lc.get("by_band")
        if isinstance(by_band, dict):
            for band, count in by_band.items():
                cnt = sum(1 for d in per_device if isinstance(d, dict) and d.get("band") == band)
                check(f"lifecycle_risk.summary.by_band[{band}]", count, cnt,
                      f"count(per_device.band=={band})")

    # --- design decisions --------------------------------------------------------------------
    dbp = _as_dict(snap.get("design_blueprint"))    # _as_dict guards the same TRUTHY-non-dict crash class as the
    dsum = _as_dict(dbp.get("summary"))             # summary blocks above (a str `summary` would crash the .get)
    decisions = dbp.get("decisions")
    if "n_decisions" in dsum and isinstance(decisions, list):
        check("design_blueprint.summary.n_decisions", dsum.get("n_decisions"), len(decisions),
              "len(design_blueprint.decisions)")

    return violations


def audit(snap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Runtime SSOT self-check for the assembly line — the field-data safety net.

    The test suite only proves SSOT-consistency on its own fixtures; a snapshot produced by
    ``cisco-assess`` on a real customer fleet is never seen by the suite. So at assembly time the
    engine reconciles its own published facts and, IF (and only if) they don't reconcile, returns a
    disclosure dict to be stamped into ``assessment_integrity`` — the SAME machine-readable channel
    the engine already uses to disclose a failed cross-axis brief, which the deck/explorer surface
    instead of rendering missing numbers as healthy zeros.

    Returns ``None`` on a clean run (the normal case) so a healthy snapshot raises NO false integrity
    alarm and grows NO new field (preserving the ``assessment_integrity not in snap`` invariant).
    """
    violations = reconcile(snap)
    if not violations:
        return None
    status_key, count_key, list_key = AUDIT_DISCLOSURE_KEYS
    return {
        status_key: "failed",
        count_key: len(violations),
        list_key: violations[:20],  # bounded so a pathological snapshot can't bloat the disclosure
    }


def summary(snap: Dict[str, Any]) -> Dict[str, Any]:
    """A compact, always-present self-verification summary for the dashboards -- the POSITIVE
    companion to :func:`audit` (which discloses only on drift). Reports how many canonical facts
    were published and whether they all reconcile to the raw evidence, so a surface can render a
    client-facing trust signal ("N headline facts self-verified against the raw evidence") without
    re-running any check itself.

    Returns ``{"verified": bool, "n_facts": int, "n_checked": int, "n_violations": int}``.
    ``n_facts`` counts the canonical facts actually PUBLISHED; ``n_checked`` counts the ones actually
    RECONCILED against raw evidence. Those are different numbers and the difference is the whole
    point: every check in :func:`reconcile` is gated on its raw basis being present, so a snapshot
    that publishes all 14 canonical blocks but carries no ``health_scores`` / ``endpoint_identity`` /
    ``lifecycle_risk.per_device`` / ``collection_completeness`` reconciles NOTHING and still had
    ``n_facts == 14`` with an empty violation list.

    ``verified`` therefore requires ``n_checked > 0`` as well as a clean run. Without that it was
    True for a snapshot nothing had been verified against, and this dict is the basis of a
    CLIENT-FACING claim -- ``docmeta.add_excellence_front`` stamps "N headline figures self-verified
    against the raw evidence -- every number in this document reconciles to one source" into every
    DOCX deliverable, and the explorer renders the same badge. A self-verification layer asserting a
    reconciliation it never performed is the failure this whole module exists to prevent, sitting at
    the top of the trust chain.

    A figure the owner itself withholds is not counted in ``n_facts`` either: every posture fact when
    the snapshot carries no ``health_scores`` list (the abstention core calls them ``not_collected``),
    and ``avg_health`` whenever :func:`fleet_avg_health` reports it ``unverified``. Counting them put
    "N headline figures self-verified" on the same DOCX page that called the average UNVERIFIED. The
    engine always writes the list and a finite average, so its ``executive_brief.ssot`` is unchanged.
    """
    snap = snap if isinstance(snap, dict) else {}
    facts = canonical_facts(snap)
    if _posture_unbacked(snap):
        for name, (path, _concept) in CANONICAL_FACTS.items():
            if _is_posture_path(path):
                facts[name] = None
    elif fleet_avg_health(snap)["state"] == "unverified":
        facts["avg_health"] = None
    ran: List[str] = []
    violations = reconcile(snap, _ran=ran)
    return {
        "verified": bool(ran) and not violations,
        "n_facts": sum(1 for value in facts.values() if value is not None),
        "n_checked": len(ran),
        "n_violations": len(violations),
    }
