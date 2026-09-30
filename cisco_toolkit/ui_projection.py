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
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
    _NA: "ssot.fleet_avg_health (avg_health; the other posture facts follow it when no device is scored)",
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
        "when failure_impact fails. Every brief value published while a failure is recorded carries this "
        "caveat.",
        ["/overview/axes", "/overview/absent_axes", "/overview/top_gating", "/overview/posture_statement"]),
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
        ["/trust/ssot/verified", "/trust/ssot/n_checked", "/trust/ssot/n_violations"]),
    _limitation(
        "measured_zero_mapping", "cisco_toolkit.ui_projection",
        "The abstention core labels a present scalar 0 or false collected_but_empty. This projection "
        "publishes it (and a fixed-shape record made only of such values) as a measured value only when no "
        "basis section is uncollected, ssot.reconcile does not reject it, and its owner's domain state does "
        "not call the input incomplete; engine_state keeps the owner's token. An empty text or mapping "
        "stays collected_but_empty.",
        ["/overview/facts", "/trust/unknown_evidence"]),
    _limitation(
        "abstention_addresses_dict_paths_only", "ssot.abstention_reason",
        "The abstention core cannot address an array element. A list item takes its list's state, then its "
        "basis sections' failure or blind-spot state, then its own type check.",
        ["/overview/axes", "/overview/top_gating", "/trust/failures/record", "/trust/unknown_evidence/sources"]),
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
        "violation or an owner fault.",
        ["/trust/census/embedded/matches_live", "/trust/ssot/stamp_matches_live",
         "/engine/snapshot_schema_supported", "/overview/top_gating", "/overview/absent_axes"]),
)
_LIMITATION_IDS = tuple(lim["id"] for lim in LIMITATIONS)

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
}


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


class _Ctx:
    def __init__(self, snap: Any) -> None:
        self.s: Dict[str, Any] = snap if isinstance(snap, dict) else {}
        self.faults: Dict[str, str] = {}
        direct, unattributed = self._call("ssot.failed_sections", ssot.failed_sections, (frozenset(), True))
        self.direct = frozenset(k for k in direct if isinstance(k, str))
        self.unattributed = bool(unattributed)
        self.fh = self._call("ssot.fleet_avg_health", ssot.fleet_avg_health,
                             {"state": "unpublished", "value": None, "n_scored": None, "n_rows": None})
        self.canon = self._call("ssot.canonical_facts", ssot.canonical_facts, {})
        raw = self._call("ssot.reconcile", ssot.reconcile, None)
        self.violations: Optional[List[str]] = None if raw is None else [str(v) for v in raw]
        self.summary: Optional[Dict[str, Any]] = self._call("ssot.summary", ssot.summary, None)
        self._abst: Dict[str, str] = {}

    def _call(self, owner: str, fn: Callable[[Any], Any], fallback: Any) -> Any:
        try:
            return fn(self.s)
        except _OWNER_FAULTS as exc:
            self.faults[owner] = _fault_text(owner, exc)
            return fallback

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
        but no attributed failure covers it, the unattributed failures are what explain it."""
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


def _typed(raw: Any, slot: str, vocab: Sequence[str] = ()) -> Tuple[bool, Any]:
    if slot == "count":
        return _count(raw)
    if slot == "score":
        return _score(raw)
    if slot == "text":
        return isinstance(raw, str), (raw if isinstance(raw, str) else None)
    if slot == "flag":
        return isinstance(raw, bool), (raw if isinstance(raw, bool) else None)
    if slot == "enum":
        ok = isinstance(raw, str) and raw in vocab
        return ok, (raw if ok else None)
    if not isinstance(raw, dict):
        return False, None
    if slot == "axis":
        sev, head, det = raw.get("severity"), raw.get("headline"), raw.get("detail")
        if isinstance(sev, str) and sev in SEVERITIES and isinstance(head, str) and isinstance(det, str):
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
        if (isinstance(sec, str) and isinstance(state, str) and state in UE_SOURCE_STATES and ok_n
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
    cav = [c for c in _LIMITATION_IDS if c in set(caveats)]
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
        label = row.get("axis") if isinstance(row, dict) and isinstance(row.get("axis"), str) else None
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
    fault = None
    try:
        live = ssot.compute_schema_census(ctx.s)
    except _OWNER_FAULTS as exc:
        live, fault = None, _fault_text(basis, exc)
    embedded_state = _state_token(ctx, ctx.abst("schema_census"))
    if live is None:
        summary = {k: _live_count(ctx, None, f"{basis}:summary.{k}", fault=fault) for k in _CENSUS_SUMMARY_KEYS}
        rows = _factlist(ctx, None, basis, [], _UV, None, reason=fault)
        return {"basis": basis, "summary": summary, "rows": rows,
                "embedded": {"state": embedded_state, "matches_live": None}}
    items = []
    for row in live["sections"]:
        key = row.get("key")
        if not isinstance(key, str):
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
        items.append({"index": i, "label": label if isinstance(label, str) else None, "classification": kind,
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
    fault = ctx.faults.get("ssot.summary") or ctx.faults.get("ssot.reconcile")
    if live is None or ctx.violations is None:
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
        texts = list(ctx.violations or ())
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


def project(snap: Any) -> Dict[str, Any]:
    """The whole ``ui_projection/1`` payload for one snapshot. Pure and total."""
    ctx = _Ctx(snap)
    return {"schema": SCHEMA, "engine": _engine(ctx), "overview": _overview(ctx), "trust": _trust(ctx)}


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


def _build_schema() -> Dict[str, Any]:
    defs: Dict[str, Any] = {
        "State": {"title": "State", "type": "string", "enum": list(STATES)},
        "WithheldState": {"title": "WithheldState", "type": "string", "enum": list(WITHHELD_STATES)},
        "AbstentionState": {"title": "AbstentionState", "type": "string", "enum": list(ssot.ABSTENTION_STATES)},
        "EngineState": {"title": "EngineState", "type": "string", "enum": list(ENGINE_STATES)},
        "EngineStateOwner": {"title": "EngineStateOwner", "type": "string", "enum": list(ENGINE_STATE_OWNERS)},
        "LimitationId": {"title": "LimitationId", "type": "string", "enum": list(_LIMITATION_IDS)},
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
    root = _closed("UiProjection", ("schema", "engine", "overview", "trust"),
                   {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"),
                    "overview": _ref("Overview"), "trust": _ref("Trust")})
    root["title"] = SCHEMA
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **root, "$defs": defs}


def ui_projection_schema() -> Dict[str, Any]:
    """The ``ui_projection/1`` JSON Schema (draft 2020-12), built fresh on every call (no shared nodes)."""
    return _copy_schema(_build_schema())


__all__ = [
    "ALWAYS_EMITTED_AXES", "AXIS_BASIS", "BRIEF_INPUTS", "CENSUS_KINDS", "COVERAGE_STATES", "DOMAIN_STATE_OWNERS",
    "ENGINE_STATES", "ENGINE_STATE_OWNERS", "FLEET_HEALTH_STATES", "HEALTH_BANDS", "JS_MAX_SAFE_INT",
    "LIFECYCLE_BAND_FACTS", "LIFECYCLE_BAND_FACTS_BY_BAND", "LIFECYCLE_BAND_ORDER", "LIMITATIONS",
    "NOT_ASSESSED_REASONS", "PHASE_CLASSIFICATIONS", "POSTURE_STATEMENT_BASIS", "RECONCILED_PATHS", "REF_ROLES",
    "SCHEMA", "SCHEMA_ID", "SEVERITIES", "SNAPSHOT_SCHEMA", "STATES", "UE_COMPLETE_STATES", "UE_SOURCE_STATES",
    "UNKNOWN_EVIDENCE_STATES", "WITHHELD_STATES", "json_pointer", "project", "project_engine", "project_overview",
    "project_trust", "ui_projection_schema",
]
