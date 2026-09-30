"""ui_projection/1 -- the ONE typed projection from a snapshot to what a screen shows (D9).

"Facts in Python, geometry in the browser." Every verdict, count, rollup, denominator, severity band
and evidence state a UI renders is decided HERE, from the engine's owners, and published in one
schema-tagged payload. The browser only lays out, sorts, filters and draws; it never aggregates, never
re-derives a headline number and never turns an absence into a value.

Slice 1 covers two screens:

* ``overview`` -- the canonical headline facts (:data:`ssot.CANONICAL_FACTS`), the fleet-health
  scoring state, the executive-brief axes / top-gating list / posture statement, and the lifecycle
  band partition;
* ``trust`` -- the live schema census, the failed-phase record, the published coverage matrix, the
  unknown-evidence summary, the SSOT self-verification, and the projection's own stated limitations;

plus an ``engine`` block naming the snapshot schema and producer versions.

Every fact travels in one envelope::

    Fact     = {state, value, subject, refs:[{pointer, role}], basis, reason?, engine_state?}
    FactList = {state, subject, refs, basis, reason?, engine_state?, items:[...]}

``state`` is one of :data:`STATES`: the engine's abstention codomain (``ssot.ABSTENTION_STATES``) plus
two domain tokens owned by ``ssot.fleet_avg_health`` (``not_assessed`` / ``unverified``). No state is
invented here. ``value`` is ``None`` unless ``state == "published"``; ``reason`` is present exactly
when it is not, in the owner's own wording. ``engine_state`` keeps the owner's raw token whenever the
projected state differs from it. ``subject`` is the RFC 6901 address of the published value (``None``
for a value an owner computes live); every ``refs`` pointer resolves in the snapshot.

How a state is decided (a scalar at dotted path P):

1. ``ssot.abstention_reason(snap, P)`` -- it already folds in the failed-phase record and the
   derived-fact basis. ``analysis_unavailable`` always wins.
2. The fleet-health posture facts defer to ``ssot.fleet_avg_health``: over a fleet with nothing scored
   a stored ``None`` / ``0`` / ``""`` is ``not_assessed``, never a measurement (G15).
3. ``not_collected`` stays a blind spot.
4. The value must pass its slot's type check (count / text / flag / closed enum / fixed record);
   anything else -- NaN, inf, a negative count, a bool count, an out-of-vocabulary band -- is
   ``unverified``: withheld, never coerced.
5. A present scalar ``0`` / ``False`` that the abstention core labels ``collected_but_empty`` is a
   MEASURED zero and is published as such (the section-level deep-empty predicate is not reused for
   scalars). An empty text stays ``collected_but_empty``.

The projection is pure and total: no I/O, no clock, no network, never mutates its input, and builds
its output from new containers after a type check per slot, so no raw subtree (and no NaN) can reach
JSON. Rows derived from snapshot KEY order are sorted by key; list order the engine wrote is kept.

The JSON Schema (draft 2020-12) is embedded (:func:`ui_projection_schema`) rather than shipped as a
data file, so the module needs no packaging manifest change. Its enums are generated from the module
constants, and ``tests/test_ui_projection.py`` holds each constant equal to its engine owner.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from cisco_toolkit import __version__ as _CODE_SCHEMA_VERSION
from cisco_toolkit import ssot

SCHEMA = "ui_projection/1"

AU = ssot.ANALYSIS_UNAVAILABLE
_PUB = "published"
_CBE = "collected_but_empty"
_NC = "not_collected"
_NA = "not_assessed"
_UV = "unverified"

#: Projected evidence states: the engine's abstention codomain + the fleet-health domain tokens.
STATES: Tuple[str, ...] = ssot.ABSTENTION_STATES + (_NA, _UV)
#: Who owns each domain token (the abstention states are owned by ``ssot.abstention_reason``).
DOMAIN_STATE_OWNERS: Dict[str, str] = {_NA: "ssot.fleet_avg_health", _UV: "ssot.fleet_avg_health"}
#: ``ssot.fleet_avg_health`` state vocabulary (not exported by its owner; held by tests).
FLEET_HEALTH_STATES: Tuple[str, ...] = ("measured", _NA, _UV, "unpublished")
#: Every raw owner token ``engine_state`` may carry.
ENGINE_STATES: Tuple[str, ...] = STATES + ("measured", "unpublished")
REF_ROLES: Tuple[str, ...] = ("subject", "basis", "failure_record", "witness", "denominator")

# Local copies of engine vocabularies; tests/test_ui_projection.py holds each equal to its owner.
SEVERITIES: Tuple[str, ...] = ("Critical", "High", "Medium", "Low", "Info")     # analyze._APP_SEV_RANK
HEALTH_BANDS: Tuple[str, ...] = tuple(ssot._HEALTH_BAND_ORDER)
COVERAGE_STATES: Tuple[str, ...] = ("covered", "not_collected", "partial", "unverified", "unparsed",
                                    "not_observed")                             # unknown_evidence._COVERAGE_STATES
UNKNOWN_EVIDENCE_STATES: Tuple[str, ...] = ("observed_no_unknowns", "observed_with_unresolved", "incomplete",
                                            "incomplete_with_unresolved", "unavailable")
UE_SOURCE_STATES: Tuple[str, ...] = ("observed", "observed_empty", "partial", "not_collected",
                                     "malformed")                               # unknown_evidence._SOURCE_STATES
SNAPSHOT_SCHEMA = "collect_parse_snapshot/1"                                    # html.snapshot_state
LIFECYCLE_BAND_FACTS: Dict[str, str] = dict(ssot._LIFECYCLE_BANDS)
NOT_ASSESSED_REASONS: Tuple[str, ...] = ("no_health_rows", "all_insufficient_data", "no_scored_rows")
PHASE_CLASSIFICATIONS: Tuple[str, ...] = ("sections", "intermediate", "non_section", "unknown")
CENSUS_KINDS: Tuple[str, ...] = ("absent", "list", "dict", "scalar")

#: Axis label -> the ``compute_executive_brief`` inputs that axis is computed from. The producer
#: publishes no per-axis basis, so this table is owned HERE and held against the producer's source by
#: an AST test (every literal ``ax("...")`` label, every basis a parameter and a phase section).
AXIS_BASIS: Dict[str, Tuple[str, ...]] = {
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
}
#: The inputs the posture statement's flags read (analyze.compute_executive_brief).
POSTURE_STATEMENT_BASIS: Tuple[str, ...] = ("health_scores", "lifecycle_risk", "segmentation",
                                            "multicast_intelligence", "migration_readiness")
#: Every brief input: an unregistered axis label fails CLOSED to all of them.
BRIEF_INPUTS: Tuple[str, ...] = tuple(sorted(set().union(*AXIS_BASIS.values(), POSTURE_STATEMENT_BASIS)))

_POSTURE_FACTS = ("avg_health", "n_critical", "n_poor", "worst_band")
_AXIS_GATING = ("Critical", "High")          # the producer's top_gating rule

#: What this projection cannot claim, stated once and addressed to the payload paths it qualifies.
LIMITATIONS: Tuple[Dict[str, Any], ...] = (
    {"id": "census_present_keys_only", "owner": "ssot.compute_schema_census",
     "text": "The census iterates only the keys present in this snapshot, so n_not_collected is 0 by "
             "construction; it is not evidence that every expected section was collected (the engine "
             "has no static expected-section registry yet).",
     "applies_to": ["/trust/census/summary/n_not_collected", "/trust/census/rows"]},
    {"id": "failure_record_written_only_on_failure", "owner": "COLLECT_PARSE_V3_23_0.main",
     "text": "assessment_integrity.failed_phases is written only when a phase failed; its absence is not "
             "a statement that every phase passed.",
     "applies_to": ["/trust/failures/record"]},
    {"id": "one_hop_failure_attribution", "owner": "ssot.failed_sections",
     "text": "A failed phase marks only the sections one hop away (ssot.PHASE_SECTIONS, "
             "ssot.DERIVED_FACT_BASIS). A section computed from a failed section's fallback is not marked: "
             "device_dossiers is not marked when failure_impact fails.",
     "applies_to": ["/overview/axes", "/overview/top_gating", "/overview/posture_statement"]},
    {"id": "axis_basis_owned_by_projection", "owner": "cisco_toolkit.ui_projection.AXIS_BASIS",
     "text": "analyze.compute_executive_brief publishes no per-axis basis. The axis-to-input table is "
             "owned by this projection and held against the producer's source by tests; an unregistered "
             "axis label fails closed to every brief input.",
     "applies_to": ["/overview/axes"]},
    {"id": "reconcile_checks_only_with_raw_basis", "owner": "ssot.reconcile",
     "text": "A reconcile check runs only when its raw basis is present. n_checked counts the checks that "
             "actually ran, and verified requires at least one.",
     "applies_to": ["/trust/ssot/verified", "/trust/ssot/n_checked"]},
    {"id": "measured_zero_mapping", "owner": "cisco_toolkit.ui_projection",
     "text": "The abstention core labels a present scalar 0 or false collected_but_empty. This projection "
             "publishes it (and a fixed-shape record made only of such values) as a measured value; "
             "engine_state keeps the owner's token. An empty text or mapping stays collected_but_empty.",
     "applies_to": ["/overview/facts"]},
    {"id": "abstention_addresses_dict_paths_only", "owner": "ssot.abstention_reason",
     "text": "The abstention core cannot address an array element. A list item takes its list's state, "
             "then its basis sections' failure or blind-spot state, then its own type check.",
     "applies_to": ["/overview/axes", "/overview/top_gating", "/trust/failures/record",
                    "/trust/unknown_evidence/sources"]},
    {"id": "coverage_matrix_shown_as_published", "owner": "coverage_matrix.compute_coverage_matrix",
     "text": "The coverage matrix is shown exactly as the engine published it and is never recomputed. The "
             "engine emits 'covered' where a coverage source (capture_integrity, parse_yield) is silent, "
             "so a covered row is not proof that those sources ran.",
     "applies_to": ["/trust/coverage_matrix"]},
)

_RECORD_ABSENT_REASON = ("no failed-phase record: assessment_integrity.failed_phases is written only when a "
                         "phase failed, so its absence is not a statement that every phase passed")


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
# per-call context: the owners' answers, computed once
# ---------------------------------------------------------------------------------------------------
class _Ctx:
    def __init__(self, snap: Any) -> None:
        self.s: Dict[str, Any] = snap if isinstance(snap, dict) else {}
        direct, unattributed = ssot.failed_sections(self.s)
        self.direct = direct
        self.unattributed = unattributed
        self.fh = ssot.fleet_avg_health(self.s)
        self.canon = ssot.canonical_facts(self.s)
        self._abst: Dict[str, str] = {}

    def abst(self, subject: str) -> str:
        if subject not in self._abst:
            self._abst[subject] = ssot.abstention_reason(self.s, subject)
        return self._abst[subject]

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
                    kind = ssot.phase_classification(label)
                    toks = ("assessment_integrity", "failed_phases", i)
                    if kind == "sections":
                        if secs & set(ssot.PHASE_SECTIONS[str(label)]):
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
        failed = sorted(set(sections) & set(self.direct))
        text = ssot._CENSUS_NOTE[AU]
        if failed:
            return f"{text}; failed sections: {', '.join(failed)}"
        if self.unattributed:
            return f"{text}; a failure could not be attributed to sections, so this empty value may be its fallback"
        return text


# ---------------------------------------------------------------------------------------------------
# slot type checks: (ok, typed value built from NEW containers)
# ---------------------------------------------------------------------------------------------------
def _count(raw: Any) -> Tuple[bool, Any]:
    if isinstance(raw, bool):
        return False, None
    if isinstance(raw, int):
        return (raw >= 0), (int(raw) if raw >= 0 else None)
    if isinstance(raw, float) and math.isfinite(raw) and raw.is_integer() and raw >= 0:
        return True, int(raw)
    return False, None


def _typed(raw: Any, slot: str, vocab: Sequence[str] = ()) -> Tuple[bool, Any]:
    if slot == "count":
        return _count(raw)
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
    return value is False or (isinstance(value, int) and not isinstance(value, bool) and value == 0)


_MEASURED_ZERO_SLOTS = frozenset({"count", "flag", "stamp", "source"})


def _unverified_reason(slot: str) -> str:
    return (f"unverified: the published value failed this projection's '{slot}' type check; it is withheld, "
            f"never coerced")


def _not_assessed_reason(ctx: _Ctx) -> str:
    posture = _get(ctx.s, ("executive_brief", "posture"))
    token = posture.get("not_assessed") if isinstance(posture, dict) else None
    tail = f"; producer reason: {token}" if isinstance(token, str) and token in NOT_ASSESSED_REASONS else ""
    return ("not assessed: no device was health-scored, so a stored value is not a measurement "
            f"(ssot.fleet_avg_health){tail}")


def _envelope(state: str, value: Any, subject: Optional[str], refs: List[Dict[str, str]], basis: str,
              owner_token: Optional[str], reason: str) -> Dict[str, Any]:
    fact: Dict[str, Any] = {"state": state, "value": value if state == _PUB else None, "subject": subject,
                            "refs": refs, "basis": basis}
    if state != _PUB:
        fact["reason"] = reason
    if owner_token is not None and owner_token != state:
        fact["engine_state"] = owner_token
    return fact


def _generic_reason(ctx: _Ctx, state: str, slot: str, sections: Iterable[str]) -> str:
    if state == AU:
        return ctx.unavailable_reason(sections)
    if state == _NA:
        return _not_assessed_reason(ctx)
    if state == _UV:
        return _unverified_reason(slot)
    return ssot._CENSUS_NOTE.get(state, ssot._CENSUS_NOTE[_NC])


# ---------------------------------------------------------------------------------------------------
# scalar facts
# ---------------------------------------------------------------------------------------------------
def _scalar(ctx: _Ctx, path: str, slot: str, basis: str, *, vocab: Sequence[str] = (),
            extra_basis: Sequence[str] = (), posture_name: Optional[str] = None,
            canonical_name: Optional[str] = None,
            witness: Sequence[Tuple[str, Sequence[Any]]] = ()) -> Dict[str, Any]:
    toks = _tokens(path)
    raw = _get(ctx.s, toks)
    raw = None if raw is _MISSING else raw
    t = ctx.abst(path)
    owner_token: Optional[str] = t
    sections = tuple(ssot.fact_basis(path)) + tuple(s for s in extra_basis if s not in ssot.fact_basis(path))
    state: Optional[str] = None
    value: Any = None

    if t == AU or any(ctx.abst(s) == AU for s in extra_basis):
        state = AU
    elif posture_name == "avg_health" and ctx.fh["state"] != "unpublished":
        owner_token = ctx.fh["state"]
        if owner_token in (_NA, _UV):
            state = owner_token
    elif (posture_name in _POSTURE_FACTS and ctx.fh["state"] == _NA
          and (raw is None or raw == "" or (_count(raw)[0] and _count(raw)[1] == 0))):
        state = _NA
    if state is None:
        if t == _NC:
            state = _NC
        else:
            ok, typed = _typed(raw, slot, vocab)
            if not ok:
                state = _UV
            elif t == _CBE and not (slot in _MEASURED_ZERO_SLOTS and _measured_zero(typed)):
                state = _CBE
            else:
                state, value = _PUB, typed
                if canonical_name is not None and ctx.canon.get(canonical_name) != typed:
                    state, value = _UV, None       # the owner's read disagrees with the typed slot
    refs = ctx.refs([("subject", toks)]
                    + [("basis", (s,)) for s in sections[1:]]
                    + ctx.failure_entries(sections, state == AU)
                    + list(witness))
    subject = json_pointer(*toks)
    return _envelope(state, value, subject, refs, basis, owner_token,
                     _generic_reason(ctx, state, slot, sections))


# ---------------------------------------------------------------------------------------------------
# lists
# ---------------------------------------------------------------------------------------------------
def _list_base(ctx: _Ctx, path: str) -> Tuple[str, str, Any]:
    """``(base state, owner token, raw)`` for a list at a dotted path (before any rollup)."""
    raw = _get(ctx.s, _tokens(path))
    raw = None if raw is _MISSING else raw
    t = ctx.abst(path)
    if t in (AU, _NC):
        return t, t, raw
    if not isinstance(raw, list):
        return _UV, t, raw
    return t, t, raw


def _factlist(ctx: _Ctx, path: str, basis: str, items: List[Dict[str, Any]], base: str, owner: str,
              rollup: Sequence[str] = (), reason: Optional[str] = None) -> Dict[str, Any]:
    toks = _tokens(path)
    rollup_failed = [s for s in rollup if ctx.abst(s) == AU]
    state = AU if rollup_failed else base
    sections = tuple(ssot.fact_basis(path)) + tuple(s for s in rollup if s not in ssot.fact_basis(path))
    refs = ctx.refs([("subject", toks)] + [("basis", (s,)) for s in sections[1:]]
                    + ctx.failure_entries(sections, state == AU))
    out: Dict[str, Any] = {"state": state, "subject": json_pointer(*toks), "refs": refs, "basis": basis}
    if state != _PUB:
        if state == AU:
            out["reason"] = ctx.unavailable_reason(sections)
            if rollup_failed:
                out["reason"] += ("; the list may be incomplete: a failed input can drop or empty an entry "
                                  f"({', '.join(sorted(rollup_failed))})")
        else:
            out["reason"] = reason or _generic_reason(ctx, state, "list", sections)
    if owner != state:
        out["engine_state"] = owner
    out["items"] = items
    return out


def _item_basis_state(ctx: _Ctx, basis: Sequence[str]) -> Optional[str]:
    states = [ctx.abst(s) for s in basis]
    if AU in states:
        return AU
    if _NC in states:
        return _NC
    return None


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
        band = name == "worst_band"
        fact = _scalar(ctx, path, "enum" if band else "count", f"ssot.canonical_facts:{path}",
                       vocab=HEALTH_BANDS if band else (), posture_name=name if name in _POSTURE_FACTS else None,
                       canonical_name=name, witness=_lineage_witness(ctx, name))
        out[name] = {"path": path, "concept": concept, "fact": fact}
    return out


def _fleet_health(ctx: _Ctx) -> Dict[str, Any]:
    fh = ctx.fh
    hs_t = ctx.abst("health_scores")
    hs_is_list = isinstance(ctx.s.get("health_scores"), list)
    block: Dict[str, Any] = {"engine_state": fh["state"]}
    for key in ("n_scored", "n_rows"):
        raw = fh.get(key)
        entries: List[Tuple[str, Sequence[Any]]] = [("basis", ("health_scores",))]
        if key == "n_scored":
            entries.append(("witness", ("executive_brief", "posture", "n_scored")))
        owner = hs_t if hs_is_list else None
        if hs_t == AU:
            state, value = AU, None
        elif raw is None:
            state, value = _NC, None
        else:
            ok, value = _count(raw)
            state = _PUB if ok else _UV
        refs = ctx.refs(entries + ctx.failure_entries(("health_scores",), state == AU))
        block[key] = _envelope(state, value, None, refs, f"ssot.fleet_avg_health:{key}", owner,
                               _generic_reason(ctx, state, "count", ("health_scores",)))
    reason = None
    if fh["state"] == _NA:
        posture = _get(ctx.s, ("executive_brief", "posture"))
        token = posture.get("not_assessed") if isinstance(posture, dict) else None
        reason = token if isinstance(token, str) and token in NOT_ASSESSED_REASONS else None
    block["not_assessed_reason"] = reason
    return block


def _axes(ctx: _Ctx) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Any]:
    path = "executive_brief.axes"
    base, owner, raw = _list_base(ctx, path)
    items: List[Dict[str, Any]] = []
    for i, row in enumerate(raw if isinstance(raw, list) else ()):
        label = row.get("axis") if isinstance(row, dict) and isinstance(row.get("axis"), str) else ""
        basis = AXIS_BASIS.get(label, BRIEF_INPUTS)
        toks = ("executive_brief", "axes", i)
        value = None
        basis_state = _item_basis_state(ctx, basis)
        if base == AU or basis_state == AU:
            state = AU                                # a failed input always wins
        elif base != _PUB:
            state = base
        elif basis_state is not None:
            state = basis_state
        else:
            ok, value = _typed(row, "axis")
            state = _PUB if ok else _UV
        refs = ctx.refs([("subject", toks)] + [("basis", (s,)) for s in basis]
                        + ctx.failure_entries(("executive_brief",) + tuple(basis), state == AU))
        fact = _envelope(state, value, json_pointer(*toks), refs, "analyze.compute_executive_brief", owner,
                         _generic_reason(ctx, state, "axis", basis))
        items.append({"index": i, "axis": label, "basis_sections": list(basis), "fact": fact})
    listing = _factlist(ctx, path, "analyze.compute_executive_brief", items, base, owner, rollup=BRIEF_INPUTS)
    return listing, items, raw


def _top_gating(ctx: _Ctx, axis_items: List[Dict[str, Any]], axes_raw: Any) -> Dict[str, Any]:
    path = "executive_brief.top_gating"
    base, owner, raw = _list_base(ctx, path)
    items: List[Dict[str, Any]] = []
    for i, text in enumerate(raw if isinstance(raw, list) else ()):
        toks = ("executive_brief", "top_gating", i)
        j: Optional[int] = None
        if isinstance(text, str) and isinstance(axes_raw, list):
            j = next((k for k, row in enumerate(axes_raw)
                      if isinstance(row, dict) and row.get("headline") == text
                      and row.get("severity") in _AXIS_GATING), None)
        entries: List[Tuple[str, Sequence[Any]]] = [("subject", toks)]
        basis: Tuple[str, ...] = ()
        value = None
        if base != _PUB:
            state = base
        elif j is None or j >= len(axis_items):
            state = _UV
        else:
            axis_item = axis_items[j]
            basis = tuple(axis_item["basis_sections"])
            entries.append(("witness", ("executive_brief", "axes", j)))
            state = axis_item["fact"]["state"]
            if state == _PUB:
                ok, value = _typed(text, "text")
                state = _PUB if ok else _UV
        refs = ctx.refs(entries + [("basis", (s,)) for s in basis]
                        + ctx.failure_entries(("executive_brief",) + basis, state == AU))
        reason = ("unverified: no Critical/High axis carries this headline (the producer's top_gating rule)"
                  if state == _UV and base == _PUB and j is None else _generic_reason(ctx, state, "text", basis))
        fact = _envelope(state, value, json_pointer(*toks), refs, "analyze.compute_executive_brief", owner,
                         reason)
        items.append({"index": i, "axis_index": j, "fact": fact})
    return _factlist(ctx, path, "analyze.compute_executive_brief", items, base, owner, rollup=BRIEF_INPUTS)


def project_overview(snap: Any) -> Dict[str, Any]:
    """The Overview screen: canonical facts, fleet-health scoring state, brief axes, lifecycle bands."""
    ctx = _Ctx(snap)
    axes, axis_items, axes_raw = _axes(ctx)
    lc_owner = "analyze.compute_lifecycle_risk"
    return {
        "facts": _overview_facts(ctx),
        "fleet_health": _fleet_health(ctx),
        "axes": axes,
        "posture_statement": _scalar(ctx, "executive_brief.posture_statement", "text",
                                     "analyze.compute_executive_brief", extra_basis=POSTURE_STATEMENT_BASIS),
        "top_gating": _top_gating(ctx, axis_items, axes_raw),
        "lifecycle": {
            "bands": [{"band": band, "fact_name": name} for name, band in LIFECYCLE_BAND_FACTS.items()],
            "of": _scalar(ctx, "lifecycle_risk.summary.n_devices", "count",
                          f"{lc_owner}:lifecycle_risk.summary.n_devices"),
            "asof": _scalar(ctx, "lifecycle_risk.summary.asof", "text", f"{lc_owner}:lifecycle_risk.summary.asof"),
        },
    }


# ---------------------------------------------------------------------------------------------------
# trust
# ---------------------------------------------------------------------------------------------------
def _census_rows_by_key(sections: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(sections, list):
        return None
    out: Dict[str, Any] = {}
    for row in sections:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or row["key"] in out:
            return None
        out[row["key"]] = row
    return out


def _census(ctx: _Ctx) -> Dict[str, Any]:
    live = ssot.compute_schema_census(ctx.s)
    rows = []
    for row in live["sections"]:
        key = row.get("key")
        if not isinstance(key, str):
            continue                                  # a non-JSON key has no RFC 6901 address
        count = row.get("count")
        rows.append({"key": key, "state": row["state"],
                     "count": count if isinstance(count, int) and not isinstance(count, bool) else None,
                     "kind": row["kind"], "note": row["note"], "pointer": json_pointer(key)})
    rows.sort(key=lambda r: r["key"])
    summary = {k: int(live["summary"].get(k, 0)) for k in
               ("n_published", "n_collected_but_empty", "n_not_collected", "n_analysis_unavailable", "n_sections")}
    embedded = ctx.s.get("schema_census")
    matches: Optional[bool] = None
    if embedded is not None:
        emb_rows = _census_rows_by_key(embedded.get("sections")) if isinstance(embedded, dict) else None
        matches = (isinstance(embedded, dict) and emb_rows is not None
                   and embedded.get("schema") == live["schema"] and embedded.get("summary") == live["summary"]
                   and emb_rows == _census_rows_by_key(live["sections"]))
    return {"basis": "ssot.compute_schema_census", "summary": summary, "rows": rows,
            "embedded": {"state": ctx.abst("schema_census"), "matches_live": matches}}


def _failures(ctx: _Ctx) -> Dict[str, Any]:
    path = "assessment_integrity.failed_phases"
    base, owner, raw = _list_base(ctx, path)
    items = []
    for i, label in enumerate(raw if isinstance(raw, list) else ()):
        kind = ssot.phase_classification(label)
        items.append({"index": i, "label": label if isinstance(label, str) else str(label),
                      "classification": kind,
                      "sections": list(ssot.PHASE_SECTIONS[str(label)]) if kind == "sections" else [],
                      "pointer": json_pointer("assessment_integrity", "failed_phases", i)})
    record = _factlist(ctx, path, "ssot.failed_sections", items, base, owner,
                       reason=_RECORD_ABSENT_REASON if base == _NC else None)
    direct = []
    for sec in sorted(str(s) for s in ctx.direct):
        direct.append({"section": sec,
                       "refs": ctx.refs([("subject", (sec,))] + ctx.failure_entries((sec,), False))})
    return {"basis": "ssot.failed_sections", "record": record, "direct_sections": direct,
            "unattributed": bool(ctx.unattributed)}


def _coverage_matrix(ctx: _Ctx) -> Dict[str, Any]:
    owner = "coverage_matrix.compute_coverage_matrix"
    out: Dict[str, Any] = {}
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained"):
        path = f"coverage_matrix.summary.{key}"
        out[key] = _scalar(ctx, path, "count", f"{owner}:{path}")
    out["by_state"] = _scalar(ctx, "coverage_matrix.summary.by_state", "by_state",
                              f"{owner}:coverage_matrix.summary.by_state")
    out["note"] = _scalar(ctx, "coverage_matrix.summary.note", "text", f"{owner}:coverage_matrix.summary.note")
    return out


def _unknown_evidence(ctx: _Ctx) -> Dict[str, Any]:
    owner = "unknown_evidence.compute_unknown_evidence"
    out: Dict[str, Any] = {}
    for key, slot, vocab in (("state", "enum", UNKNOWN_EVIDENCE_STATES), ("n_events", "count", ()),
                             ("n_unresolved", "count", ()), ("source_coverage_complete", "flag", ()),
                             ("claim_scope", "text", ()), ("note", "text", ())):
        path = f"unknown_evidence.summary.{key}"
        out[key] = _scalar(ctx, path, slot, f"{owner}:{path}", vocab=vocab)
    path = "unknown_evidence.sources"
    base, token, raw = _list_base(ctx, path)
    items = []
    for i, row in enumerate(raw if isinstance(raw, list) else ()):
        toks = ("unknown_evidence", "sources", i)
        value = None
        if base != _PUB:
            state = base
        else:
            ok, value = _typed(row, "source")
            state = _PUB if ok else _UV
        refs = ctx.refs([("subject", toks)] + ctx.failure_entries(("unknown_evidence",), state == AU))
        items.append({"index": i, "fact": _envelope(state, value, json_pointer(*toks), refs, f"{owner}:{path}",
                                                    token, _generic_reason(ctx, state, "source", ()))})
    out["sources"] = _factlist(ctx, path, f"{owner}:{path}", items, base, token)
    return out


def _ssot_block(ctx: _Ctx) -> Dict[str, Any]:
    live = ssot.summary(ctx.s)
    violations = [str(v) for v in ssot.reconcile(ctx.s)]
    live_stamp = {"verified": bool(live["verified"]), "n_facts": int(live["n_facts"]),
                  "n_checked": int(live["n_checked"]), "n_violations": int(live["n_violations"])}
    stamp = _scalar(ctx, "executive_brief.ssot", "stamp", "ssot.summary (stamped by COLLECT_PARSE_V3_23_0.main)")
    return {"basis": "ssot.summary", **live_stamp, "violations": violations, "engine_stamp": stamp,
            "stamp_matches_live": (stamp["value"] == live_stamp) if stamp["state"] == _PUB else None}


def project_trust(snap: Any) -> Dict[str, Any]:
    """The Trust screen: census, failure record, coverage matrix, unknown evidence, SSOT verification."""
    ctx = _Ctx(snap)
    return {
        "census": _census(ctx),
        "failures": _failures(ctx),
        "coverage_matrix": _coverage_matrix(ctx),
        "unknown_evidence": _unknown_evidence(ctx),
        "ssot": _ssot_block(ctx),
        "limitations": copy.deepcopy(list(LIMITATIONS)),
    }


# ---------------------------------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------------------------------
def project_engine(snap: Any) -> Dict[str, Any]:
    """Which snapshot schema and producer versions this payload was projected from."""
    ctx = _Ctx(snap)
    out: Dict[str, Any] = {}
    for key, owner in (("schema", "html.snapshot_state"), ("script_version", "html.snapshot_state"),
                       ("generated_at", "html.snapshot_state"), ("collected_at", "COLLECT_PARSE_V3_23_0.main")):
        out["snapshot_schema" if key == "schema" else key] = _scalar(ctx, key, "text", f"{owner}:{key}")
    stamp = out["snapshot_schema"]
    out["snapshot_schema_supported"] = (stamp["value"] == SNAPSHOT_SCHEMA) if stamp["state"] == _PUB else None
    out["code_schema_version"] = str(_CODE_SCHEMA_VERSION)
    return out


def project(snap: Any) -> Dict[str, Any]:
    """The whole ``ui_projection/1`` payload for one snapshot. Pure and total."""
    return {"schema": SCHEMA, "engine": project_engine(snap), "overview": project_overview(snap),
            "trust": project_trust(snap)}


# ---------------------------------------------------------------------------------------------------
# JSON Schema (draft 2020-12), generated from the module constants
# ---------------------------------------------------------------------------------------------------
def _allof(base: str, value: Dict[str, Any]) -> Dict[str, Any]:
    return {"allOf": [{"$ref": f"#/$defs/{base}"}, {"properties": {"value": value}}]}


def _nullable_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {"anyOf": [{"type": "null"}, obj]}


def _list_of(item: Dict[str, Any]) -> Dict[str, Any]:
    return {"allOf": [{"$ref": "#/$defs/factList"}, {"properties": {"items": {"items": item}}}]}


def _closed(required: Sequence[str], properties: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(required), "properties": properties}


_NONNEG_INT = {"type": "integer", "minimum": 0}
_REF = {name: {"$ref": f"#/$defs/{name}"} for name in
        ("pointer", "countFact", "textFact", "flagFact", "factList", "canon", "canonBand")}


def _build_schema() -> Dict[str, Any]:
    fact_props = {"state": {"$ref": "#/$defs/state"}, "subject": {"anyOf": [_REF["pointer"], {"type": "null"}]},
                  "refs": {"type": "array", "items": {"$ref": "#/$defs/ref"}},
                  "basis": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1},
                  "engine_state": {"$ref": "#/$defs/engineState"}}
    defs: Dict[str, Any] = {
        "state": {"enum": list(STATES)},
        "abstentionState": {"enum": list(ssot.ABSTENTION_STATES)},
        "engineState": {"enum": list(ENGINE_STATES)},
        "pointer": {"type": "string", "pattern": "^(/([^~/]|~[01])*)*$"},
        "ref": _closed(("pointer", "role"), {"pointer": _REF["pointer"], "role": {"enum": list(REF_ROLES)}}),
        "fact": {
            "type": "object", "additionalProperties": False,
            "required": ["state", "value", "subject", "refs", "basis"],
            "properties": {**fact_props, "value": True},
            "if": {"properties": {"state": {"const": _PUB}}},
            "then": {"not": {"required": ["reason"]}, "properties": {"value": {"not": {"type": "null"}}}},
            "else": {"required": ["reason"], "properties": {"value": {"type": "null"}}},
        },
        "factList": {
            "type": "object", "additionalProperties": False,
            "required": ["state", "subject", "refs", "basis", "items"],
            "properties": {**fact_props, "items": {"type": "array"}},
            "if": {"properties": {"state": {"const": _PUB}}},
            "then": {"not": {"required": ["reason"]}, "properties": {"items": {"minItems": 1}}},
            "else": {"required": ["reason"]},
        },
        "countFact": _allof("fact", {"type": ["integer", "null"], "minimum": 0}),
        "textFact": _allof("fact", {"type": ["string", "null"]}),
        "flagFact": _allof("fact", {"type": ["boolean", "null"]}),
        "bandFact": _allof("fact", {"enum": list(HEALTH_BANDS) + [None]}),
        "ueStateFact": _allof("fact", {"enum": list(UNKNOWN_EVIDENCE_STATES) + [None]}),
        "axisFact": _allof("fact", _nullable_object(_closed(
            ("severity", "headline", "detail"),
            {"severity": {"enum": list(SEVERITIES)}, "headline": {"type": "string"},
             "detail": {"type": "string"}}))),
        "byStateFact": _allof("fact", _nullable_object(
            {"type": "object", "propertyNames": {"enum": list(COVERAGE_STATES)},
             "additionalProperties": _NONNEG_INT})),
        "stampFact": _allof("fact", _nullable_object(_closed(
            ("verified", "n_facts", "n_checked", "n_violations"),
            {"verified": {"type": "boolean"}, "n_facts": _NONNEG_INT, "n_checked": _NONNEG_INT,
             "n_violations": _NONNEG_INT}))),
        "sourceFact": _allof("fact", _nullable_object(_closed(
            ("section", "state", "records_examined", "detail_complete"),
            {"section": {"type": "string"}, "state": {"enum": list(UE_SOURCE_STATES)},
             "records_examined": _NONNEG_INT, "detail_complete": {"type": "boolean"}}))),
        "canon": _closed(("path", "concept", "fact"), {"path": {"type": "string"}, "concept": {"type": "string"},
                                                       "fact": _REF["countFact"]}),
        "canonBand": _closed(("path", "concept", "fact"), {"path": {"type": "string"},
                                                           "concept": {"type": "string"},
                                                           "fact": {"$ref": "#/$defs/bandFact"}}),
    }
    defs["engine"] = _closed(
        ("snapshot_schema", "script_version", "generated_at", "collected_at", "snapshot_schema_supported",
         "code_schema_version"),
        {"snapshot_schema": _REF["textFact"], "script_version": _REF["textFact"],
         "generated_at": _REF["textFact"], "collected_at": _REF["textFact"],
         "snapshot_schema_supported": {"type": ["boolean", "null"]}, "code_schema_version": {"type": "string"}})
    facts = {name: (_REF["canonBand"] if name == "worst_band" else _REF["canon"]) for name in ssot.CANONICAL_FACTS}
    defs["overview"] = _closed(
        ("facts", "fleet_health", "axes", "posture_statement", "top_gating", "lifecycle"),
        {"facts": _closed(tuple(ssot.CANONICAL_FACTS), facts),
         "fleet_health": _closed(
             ("engine_state", "n_scored", "n_rows", "not_assessed_reason"),
             {"engine_state": {"enum": list(FLEET_HEALTH_STATES)}, "n_scored": _REF["countFact"],
              "n_rows": _REF["countFact"], "not_assessed_reason": {"enum": list(NOT_ASSESSED_REASONS) + [None]}}),
         "axes": _list_of(_closed(("index", "axis", "basis_sections", "fact"),
                                  {"index": _NONNEG_INT, "axis": {"type": "string"},
                                   "basis_sections": {"type": "array", "items": {"type": "string"}},
                                   "fact": {"$ref": "#/$defs/axisFact"}})),
         "posture_statement": _REF["textFact"],
         "top_gating": _list_of(_closed(("index", "axis_index", "fact"),
                                        {"index": _NONNEG_INT, "axis_index": {"type": ["integer", "null"],
                                                                              "minimum": 0},
                                         "fact": _REF["textFact"]})),
         "lifecycle": _closed(
             ("bands", "of", "asof"),
             {"bands": {"type": "array", "items": _closed(
                 ("band", "fact_name"), {"band": {"enum": list(LIFECYCLE_BAND_FACTS.values())},
                                         "fact_name": {"enum": list(LIFECYCLE_BAND_FACTS)}})},
              "of": _REF["countFact"], "asof": _REF["textFact"]})})
    summary_keys = ("n_published", "n_collected_but_empty", "n_not_collected", "n_analysis_unavailable",
                    "n_sections")
    defs["trust"] = _closed(
        ("census", "failures", "coverage_matrix", "unknown_evidence", "ssot", "limitations"),
        {"census": _closed(
            ("basis", "summary", "rows", "embedded"),
            {"basis": {"const": "ssot.compute_schema_census"},
             "summary": _closed(summary_keys, {k: _NONNEG_INT for k in summary_keys}),
             "rows": {"type": "array", "items": _closed(
                 ("key", "state", "count", "kind", "note", "pointer"),
                 {"key": {"type": "string"}, "state": {"$ref": "#/$defs/abstentionState"},
                  "count": {"type": ["integer", "null"], "minimum": 0}, "kind": {"enum": list(CENSUS_KINDS)},
                  "note": {"type": "string"}, "pointer": _REF["pointer"]})},
             "embedded": _closed(("state", "matches_live"),
                                 {"state": {"$ref": "#/$defs/abstentionState"},
                                  "matches_live": {"type": ["boolean", "null"]}})}),
         "failures": _closed(
             ("basis", "record", "direct_sections", "unattributed"),
             {"basis": {"const": "ssot.failed_sections"},
              "record": _list_of(_closed(("index", "label", "classification", "sections", "pointer"),
                                         {"index": _NONNEG_INT, "label": {"type": "string"},
                                          "classification": {"enum": list(PHASE_CLASSIFICATIONS)},
                                          "sections": {"type": "array", "items": {"type": "string"}},
                                          "pointer": _REF["pointer"]})),
              "direct_sections": {"type": "array", "items": _closed(
                  ("section", "refs"), {"section": {"type": "string"},
                                        "refs": {"type": "array", "items": {"$ref": "#/$defs/ref"}}})},
              "unattributed": {"type": "boolean"}}),
         "coverage_matrix": _closed(
             ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"),
             {"n_devices": _REF["countFact"], "n_axes": _REF["countFact"], "n_rows": _REF["countFact"],
              "n_covered": _REF["countFact"], "n_abstained": _REF["countFact"],
              "by_state": {"$ref": "#/$defs/byStateFact"}, "note": _REF["textFact"]}),
         "unknown_evidence": _closed(
             ("state", "n_events", "n_unresolved", "source_coverage_complete", "claim_scope", "note", "sources"),
             {"state": {"$ref": "#/$defs/ueStateFact"}, "n_events": _REF["countFact"],
              "n_unresolved": _REF["countFact"], "source_coverage_complete": _REF["flagFact"],
              "claim_scope": _REF["textFact"], "note": _REF["textFact"],
              "sources": _list_of(_closed(("index", "fact"), {"index": _NONNEG_INT,
                                                              "fact": {"$ref": "#/$defs/sourceFact"}}))}),
         "ssot": _closed(
             ("basis", "verified", "n_facts", "n_checked", "n_violations", "violations", "engine_stamp",
              "stamp_matches_live"),
             {"basis": {"const": "ssot.summary"}, "verified": {"type": "boolean"}, "n_facts": _NONNEG_INT,
              "n_checked": _NONNEG_INT, "n_violations": _NONNEG_INT,
              "violations": {"type": "array", "items": {"type": "string"}},
              "engine_stamp": {"$ref": "#/$defs/stampFact"},
              "stamp_matches_live": {"type": ["boolean", "null"]}}),
         "limitations": {"type": "array", "items": _closed(
             ("id", "owner", "text", "applies_to"),
             {"id": {"enum": [lim["id"] for lim in LIMITATIONS]}, "owner": {"type": "string"},
              "text": {"type": "string"}, "applies_to": {"type": "array", "items": _REF["pointer"]}})}})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:cisco-toolkit:ui_projection:1",
        "title": SCHEMA,
        "type": "object", "additionalProperties": False,
        "required": ["schema", "engine", "overview", "trust"],
        "properties": {"schema": {"const": SCHEMA}, "engine": {"$ref": "#/$defs/engine"},
                       "overview": {"$ref": "#/$defs/overview"}, "trust": {"$ref": "#/$defs/trust"}},
        "$defs": defs,
    }


_SCHEMA: Dict[str, Any] = _build_schema()


def ui_projection_schema() -> Dict[str, Any]:
    """The ``ui_projection/1`` JSON Schema (draft 2020-12), as a fresh deep copy."""
    return copy.deepcopy(_SCHEMA)


__all__ = [
    "AXIS_BASIS", "BRIEF_INPUTS", "CENSUS_KINDS", "COVERAGE_STATES", "DOMAIN_STATE_OWNERS", "ENGINE_STATES",
    "FLEET_HEALTH_STATES", "HEALTH_BANDS", "LIFECYCLE_BAND_FACTS", "LIMITATIONS", "NOT_ASSESSED_REASONS",
    "PHASE_CLASSIFICATIONS", "POSTURE_STATEMENT_BASIS", "REF_ROLES", "SCHEMA", "SEVERITIES", "SNAPSHOT_SCHEMA",
    "STATES", "UE_SOURCE_STATES", "UNKNOWN_EVIDENCE_STATES", "json_pointer", "project", "project_engine",
    "project_overview", "project_trust", "ui_projection_schema",
]
