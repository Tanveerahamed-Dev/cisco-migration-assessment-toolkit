"""The snapshot-reporting layer: build the pre/post-cutover snapshot (snapshot_state - the JSON
contract embedded in the HTML and written beside every workbook) and render outputs from it - the
Blast-Radius Explorer HTML (write_html_explorer) and the '--compare OLD NEW' diff workbook
(write_diff_workbook). Extracted verbatim from COLLECT_PARSE_V3_23_0.py across PHASE 2.7 steps
29-30 (behaviour byte-identical). Depends on openpyxl + stdlib + the package's model/__version__."""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import PurePath
from typing import Any, Dict, List, Optional

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from cisco_toolkit import __version__
from cisco_toolkit.model import DevicePhysical, InterfaceData
from cisco_toolkit.brand_tokens import WORKBOOK_NAVY_HEX
from cisco_toolkit.textutils import is_finite_num, xml_safe as _cv

logger = logging.getLogger(__name__)


_DIFF_FIELDS = ["status", "switchport_mode", "vlan", "trunk_native_vlan",
                "trunk_allowed_vlans", "stp_blocked", "port_channel",
                "svi_ip", "hsrp_behavior", "subnet_primary_route"]

def _macset(s) -> set:
    """The MAC-address set of an interface's mac field, tolerant of a malformed value.

    `s or ""` guards None/empty but keeps a TRUTHY non-str (an int, or the `float('inf')` json.loads
    makes of a bare JSON `Infinity`), and `re.split` then raises `TypeError: expected string or
    bytes-like object` -- aborting the whole --compare workbook. A container is not a MAC list at all
    (-> empty set, i.e. 'not observed'); a non-str SCALAR is stringified so a value that really was a
    single MAC-ish token is still compared rather than silently dropped."""
    if not isinstance(s, str):
        s = "" if s is None or isinstance(s, (dict, list, tuple, set)) else str(s)
    return set(t for t in re.split(r"[,\s;]+", s) if t)


# Pre/post-cutover VALIDATION (NEW-V3.23.106). Beyond the raw interface/SVI/MAC diff, compare the
# COMPUTED analysis between two snapshots so an operator can answer "did the cutover make anything
# worse?": per-switch health-band shifts and the consolidated punch-list findings that OPENED vs
# RESOLVED (the punch-list already rolls up all finding sources, deduped + severity-ranked). Pure
# read of two snapshot_state() dicts; tolerant of older snapshots that lack the computed keys.
# 'Insufficient Data' is deliberately ABSENT: it is a coverage state, not a health-scale point (ssot.py:60-63), so
# transitions into/out of it are handled as coverage_shifts, never ranked as better/worse than a real band.
_BAND_RANK = {"Excellent": 0, "Good": 1, "Fair": 2, "Poor": 3, "Critical": 4}
_FIND_SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


# Renamed-title aliases: a pure title REWORDING (same detector, same measure, same scope semantics)
# must not churn the cutover-validation delta as resolved+opened when an OLD-engine baseline snapshot
# is compared against a NEW-engine one (PR-#396 review: the native-VLAN-1 rename flipped an
# identical-network compare from CLEAN to REVIEW). Each entry maps the pre-rename numbered-title form
# onto the CURRENT wording BEFORE keying; the count and device-set still participate in the key, so a
# genuine scope change (different N / different devices) keeps showing honestly as resolved+opened.
_TITLE_RENAMES = (
    (re.compile(r"^Native VLAN 1 on (\d+) inter-switch trunk\(s\)$"),
     r"Native VLAN 1 on \1 operationally-trunking port(s)"),
)


def _canon_title(title: str) -> str:
    for rx, repl in _TITLE_RENAMES:
        title = rx.sub(repl, title)
    return title


def _as_dict(x):
    """A snapshot section coerced to a dict. `... or {}` only guards FALSY values, so a truthy non-dict (a list/
    scalar from a malformed --compare/--trend snapshot) flowed into .values()/set() and raised (audit-5 totality);
    `.get(k, {})` likewise returns None for a present-but-null key."""
    return x if isinstance(x, dict) else {}


def _renderable_num(v) -> bool:
    """True for a number that arithmetic and cell-rendering can both survive.

    `isinstance(v, (int, float))` is NOT enough for a value read out of an untrusted snapshot:
    `json.loads` accepts integer literals of unbounded precision (`10**400` -> OverflowError on any
    float conversion, including `sum()/len()` and openpyxl's cell writer) and the bare `Infinity` /
    `-Infinity` / `NaN` tokens (which propagate through an average into a rendered figure).

    Delegates to the ONE owner (textutils.is_finite_num, shared with ssot.reconcile and causal), and
    keeps `bool` accepted here only because the pre-existing `isinstance(v, (int, float))` filter this
    replaces accepted it (bool is an int subclass) and a band tally must not change silently."""
    return isinstance(v, bool) or is_finite_num(v)


def _skey(x):
    """A TOTAL sort key for a set of snapshot-derived labels of possibly MIXED type.

    `sorted()` over a set built from device-derived leaves assumes every member is the same type, but a
    JSON snapshot can carry `"switch": 10` on one row and `"switch": "10"` on the next (a foreign-tool
    export, an older schema, a hand-trim) -- and Python 3 raises
    `TypeError: '<' not supported between instances of 'str' and 'int'`. Unlike the unhashable case this
    needs no poison at all: two ordinary, JSON-legal rows are enough.

    Strings sort FIRST and EXACTLY as before (the `(0, x)` branch compares the raw str), so the ordering
    of every well-formed snapshot is byte-identical; non-strings are grouped after them and ordered by
    their repr, which is deterministic and never raises."""
    return (0, x) if isinstance(x, str) else (1, str(x))


def _hkey(x):
    """A HASHABLE form of a snapshot LEAF about to be used as a dict key or as the left operand of an
    `in <dict>` test. _as_dict/_as_list guard the section's SHAPE; this guards the leaf inside a row.

    A dict/list where a label is expected (`health_scores[].switch`, `migration_readiness[].readiness`)
    is unhashable, and `{r.get('switch'): r}` / `r.get('readiness') in readiness` then raises
    `TypeError: unhashable type: 'dict'` -- which ABORTS write_diff_workbook and write_campaign_workbook
    (the --compare / --trend deliverables) and 500s the webapp diff/trend routes on every later read of
    a stored snapshot. Hashable values pass through UNCHANGED (keys, dedup and sort order over real data
    are untouched); only the unhashable poison is stringified, so it stays a DISTINCT key rather than
    silently merging rows or dropping a device. Twin of design_advisor._hkey (audit-7)."""
    try:
        hash(x)
        return x
    except TypeError:
        return str(x)


def _as_list(x):
    """A snapshot section coerced to a list -- the list-shaped twin of _as_dict, same reasoning: `... or []`
    only guards FALSY values, so a TRUTHY non-list (`health_scores: 5` in a hand-crafted upload) survived the
    guard and raised on the next `for r in ...` / `list(...)`. On the webapp side that is a STORED availability
    DoS: the upload is accepted (the only check is dict + a 'devices' key) and then 500s the unwrapped
    /explorer, /api/compare and /trend routes on every later read.

    Identical to `(x or [])` for every list/None input, so well-formed output is unchanged. A wrong-typed
    DICT section also degrades identically: iterating a dict yielded str keys, which the element-level
    `isinstance(r, dict)` filters already dropped."""
    return x if isinstance(x, list) else []


_SECTION_TYPES = {
    "health_scores": list,
    "punchlist": list,
    "migration_readiness": list,
    "lifecycle_risk": dict,
}


def _schema_status(value: Any) -> dict:
    """Normalize an optional caller-provided schema-compatibility result.

    The CLI owns the exact file paths and therefore remains the authority that can compare their
    schema versions before loading them.  The reporting layer accepts either the historic
    ``(status, message)`` tuple or a mapping and preserves an explicit ``override`` marker.  An
    absent value is not invented here.
    """
    if isinstance(value, dict):
        return {
            "status": str(value.get("status") or "").strip().lower(),
            "message": str(value.get("message") or ""),
            "override": bool(value.get("override") or value.get("overridden")),
        }
    if isinstance(value, (list, tuple)) and value:
        return {
            "status": str(value[0] or "").strip().lower(),
            "message": str(value[1] or "") if len(value) > 1 else "",
            "override": False,
        }
    if isinstance(value, str) and value.strip():
        return {"status": value.strip().lower(), "message": "", "override": False}
    return {}


def _analysis_integrity(snap: Any, required_sections=()) -> dict:
    """Machine-readable assessment-integrity view used by every decision renderer in this module.

    ``assessment_integrity.failed_phases`` is authoritative even when the failed producer returned
    an empty fallback.  Top-level ``_unavailable`` sentinels and required-but-missing analysis
    sections are folded into the same channel.  The helper deliberately reports *all* failed phases:
    a report may still render the observations that remain valid, but it cannot certify the run as
    clean while its own snapshot says part of the assessment failed.
    """
    s = snap if isinstance(snap, dict) else {}
    integrity = _as_dict(s.get("assessment_integrity"))
    failures: List[str] = []
    raw_failed = integrity.get("failed_phases")
    if isinstance(raw_failed, list):
        failures.extend(f"phase failed: {str(p)}" for p in raw_failed if str(p).strip())
    elif raw_failed:
        failures.append(f"phase failed: {str(raw_failed)}")
    for key, value in integrity.items():
        if key in ("failed_phases", "n_violations"):
            continue
        if str(value).strip().lower() in ("failed", "compute_failed", "unavailable", "error"):
            failures.append(f"{key}: {value}")
    for key, value in s.items():
        if isinstance(value, dict) and value.get("_unavailable"):
            failures.append(f"{key}: unavailable")
    for key in required_sections:
        expected = _SECTION_TYPES.get(str(key), object)
        if key not in s or not isinstance(s.get(key), expected):
            failures.append(f"{key}: missing or unusable")
    # Stable order, no duplicate disclosure when a sentinel and the integrity map name the same block.
    failures = list(dict.fromkeys(failures))
    return {"ok": not failures, "failures": failures}


def _section_available(snap: dict, key: str, phase_tokens=()) -> bool:
    """Whether a list-shaped analysis section is safe to delta.

    A failed producer commonly leaves the exact same ``[]`` as a legitimate clean computation.  The
    failed-phase channel is therefore part of availability; without it, comparing a healthy baseline
    to a failed empty fallback fabricates that every old finding was resolved.
    """
    if key not in snap or not isinstance(snap.get(key), list):
        return False
    failures = _analysis_integrity(snap).get("failures") or []
    def _phase_key(value: Any) -> str:
        return "".join(ch for ch in str(value).lower() if ch.isalnum())

    lowered = [_phase_key(f) for f in failures]
    return not any(any(_phase_key(tok) in f for tok in phase_tokens) for f in lowered)


def _finding_key(f: dict) -> tuple:
    """Stable identity for a punch-list finding across two runs: (category, FULL title, device-set).
    The title is intentionally NOT digit-normalized: stripping digits collapsed DISTINCT per-identifier
    findings that differ only by an embedded id (e.g. 'Fake FHRP redundancy (VLAN 20)' vs '(VLAN 21)'
    on the same gateways) into one key, which could hide a real fix-and-new-break swap as 'no change'
    in the cutover-validation verdict. Device order is normalized so the same finding on the same
    devices matches regardless of listing order; an aggregated finding whose count changes honestly
    shows as resolved+opened (its scope genuinely changed). The ONLY title rewriting applied is the
    _TITLE_RENAMES alias table above (pre-rename wording -> current wording), which is not a
    normalization: it never merges two distinct findings, it only keeps one finding's identity stable
    across an engine-version rename."""
    # _as_list (not `or []`): a ROW-INNER scalar -- a well-formed finding whose 'devices' is `5` -- survives
    # `or []` and raises on `for d in 5`, so one poisoned punch-list row 500s /api/compare and /trend.
    devs = tuple(sorted(str(d) for d in _as_list(f.get("devices"))))
    return (str(f.get("category", "")), _canon_title(str(f.get("title", ""))), devs)


_DEVICES_CELL_WIDTH = 60


def _devices_cell(devices, width: int = _DEVICES_CELL_WIDTH) -> str:
    """A finding's device list rendered for the Findings Delta 'Devices' column, WITH the house
    ``(+N more)`` disclosure when it does not fit.

    The raw ``", ".join(...)[:60]`` this replaces cut mid-token and said nothing about it, so a
    finding on 9 devices rendered as ``MERIDIAN-SW-171, ..., DS03-DC`` -- a silent cap in a
    CUTOVER-GATE artifact, and the reader's two wrong conclusions are (a) the finding is scoped to
    the devices shown and (b) ``DS03-DC`` is a hostname (it is not; it is the front half of one).
    Measured on the real Meridian reference snapshot: 109 of 1805 punch-list findings, and 11 of 115 in
    webapp/sample_data/sample_fleet.snapshot.json.

    Truncation now lands on a whole-device boundary and the remainder is COUNTED, never dropped
    silently. ``_as_list`` (not ``or []``) for the same reason ``_finding_key`` uses it: a row-inner
    scalar ``devices: 5`` survives ``or []`` and raises on ``for d in 5``."""
    names = [str(d) for d in _as_list(devices)]
    if not names:
        return ""
    joined = ", ".join(names)
    if len(joined) <= width:
        return joined
    shown: List[str] = []
    used = 0
    for n in names:
        add = len(n) + (2 if shown else 0)
        if shown and used + add > width:
            break
        shown.append(n)
        used += add
    if not shown:                                  # one device whose name alone exceeds the width
        shown = [names[0]]
    hidden = len(names) - len(shown)
    return ", ".join(shown) + (f" (+{hidden} more)" if hidden else "")


def compute_snapshot_delta(old: dict, new: dict, *, source_binding: Optional[dict] = None,
                           schema_status: Any = None) -> dict:
    """Migration-validation delta between two snapshots: switch/interface counts, per-switch health-band
    shifts (regressed vs improved), punch-list findings opened vs resolved, and an overall verdict.
    Returns a dict.  Missing/failed computed sections abstain and make the overall result
    ``INDETERMINATE``; they are never interpreted as a clean empty result.

    ``source_binding`` and ``schema_status`` are optional caller-owned provenance.  The file-loading
    caller can supply exact input byte hashes; when present they are copied into the returned result
    and into the workbook rather than being replaced by a weaker re-serialization hash.
    """
    old = old if isinstance(old, dict) else {}            # total: the --compare/--trend path may hand us a
    new = new if isinstance(new, dict) else {}            # non-dict (a JSON file that parsed to null/[]/scalar)
    od, nd = _as_dict(old.get("devices")), _as_dict(new.get("devices"))
    oi, ni = _as_dict(old.get("interfaces")), _as_dict(new.get("interfaces"))
    old_integrity = _analysis_integrity(old, ("health_scores", "punchlist"))
    new_integrity = _analysis_integrity(new, ("health_scores", "punchlist"))
    schema = _schema_status(schema_status)
    integrity_failures = ([f"before: {f}" for f in old_integrity["failures"]]
                          + [f"after: {f}" for f in new_integrity["failures"]])
    if schema and schema.get("status") not in ("", "ok"):
        qualifier = " (explicitly overridden)" if schema.get("override") else ""
        integrity_failures.append(
            f"schema compatibility {schema.get('status')}{qualifier}: "
            f"{schema.get('message') or 'cross-input compatibility was not proven'}")

    # ---- health-band shifts (per switch present in BOTH runs) ----
    # isinstance guard: a null element in the list (hand-trimmed / older-schema snapshot fed to --compare/--trend)
    # must degrade, not AttributeError on r.get (audit-4 #15). The ELEMENT filter was present but the SECTION
    # was not coerced -- `health_scores: 5` survives `or []` and dies on `for r in 5` (_as_list, both operands:
    # a guard on only `old` leaves the identical crash reachable through `new` on the same route).
    # _hkey on the KEY leaf: an unhashable dict/list `switch` raised TypeError here, aborting the whole
    # --compare workbook (and 500ing the webapp diff route) on a snapshot that is stored and re-read.
    health_comparable = (
        _section_available(old, "health_scores", ("health score",))
        and _section_available(new, "health_scores", ("health score",))
    )
    oh = ({_hkey(r.get("switch")): r for r in _as_list(old.get("health_scores")) if isinstance(r, dict)}
          if health_comparable else {})
    nh = ({_hkey(r.get("switch")): r for r in _as_list(new.get("health_scores")) if isinstance(r, dict)}
          if health_comparable else {})
    regressed: List[dict] = []
    improved: List[dict] = []
    coverage_shifts: List[dict] = []   # transitions in/out of 'Insufficient Data' (coverage events, not health)
    for sw in sorted(set(oh) & set(nh), key=_skey):     # _skey: mixed-type switch labels must not raise
        ob, nb = oh[sw].get("band", ""), nh[sw].get("band", "")
        if ob == nb:
            continue
        # 'Insufficient Data' is a COVERAGE state, not a point on the health scale (ssot.py:60-63: it never counts
        # as the worst band). A shift into/out of it is a coverage change, NOT a health improvement/regression --
        # ranking it worse-than-Critical made 'Insufficient Data -> Critical' read 'improved' + CLEAN, i.e. a
        # newly-online Critical box certified as an improvement at the cutover gate (audit-4 #5).
        if ob == "Insufficient Data" or nb == "Insufficient Data":
            coverage_shifts.append({"switch": sw, "old_band": ob, "new_band": nb,
                                    "old_score": oh[sw].get("score", ""), "new_score": nh[sw].get("score", ""),
                                    "kind": "went_dark" if nb == "Insufficient Data" else "newly_assessed"})
            continue
        orank, nrank = _BAND_RANK.get(ob, 9), _BAND_RANK.get(nb, 9)
        if nrank == orank:
            continue
        row = {"switch": sw, "old_band": ob, "new_band": nb,
               "old_score": oh[sw].get("score", ""), "new_score": nh[sw].get("score", "")}
        (regressed if nrank > orank else improved).append(row)
    regressed.sort(key=lambda r: -_BAND_RANK.get(r["new_band"], 0))
    # coverage events that must keep the verdict off CLEAN: a device gone dark (lost visibility at cutover) or one
    # newly collected and found Critical/Poor (a real problem just revealed).
    n_went_dark = sum(1 for c in coverage_shifts if c["kind"] == "went_dark")
    newly_bad = [c for c in coverage_shifts if c["kind"] == "newly_assessed" and c["new_band"] in ("Critical", "Poor")]

    # ---- punch-list findings opened vs resolved ----
    findings_comparable = (
        _section_available(old, "punchlist", ("punch-list", "punchlist"))
        and _section_available(new, "punchlist", ("punch-list", "punchlist"))
    )
    o_find = ({_finding_key(f): f for f in _as_list(old.get("punchlist")) if isinstance(f, dict)}
              if findings_comparable else {})
    n_find = ({_finding_key(f): f for f in _as_list(new.get("punchlist")) if isinstance(f, dict)}
              if findings_comparable else {})
    # fully-deterministic order (set-difference iteration order is unstable): severity, then the
    # finding's stable identity, so two runs of the diff workbook are byte-reproducible.
    def _fsort(f: dict) -> tuple:
        return (_FIND_SEV_RANK.get(f.get("severity", ""), 9), _finding_key(f))
    opened = sorted((n_find[k] for k in (set(n_find) - set(o_find))), key=_fsort)
    resolved = sorted((o_find[k] for k in (set(o_find) - set(n_find))), key=_fsort)
    n_opened_high = sum(1 for f in opened if f.get("severity") in ("Critical", "High"))

    # ---- computed reachability what-if (W2): did the change DEFINITIVELY break a previously-working flow? ----
    # The native RIB->FIB differential (the offline Batfish-peer); coverage-honest, so only definitive
    # newly_blocked flows count toward the verdict -- ambiguous/incomplete pairs stay 'inconclusive'.
    try:
        from cisco_toolkit import fib
        rdelta = fib.reachability_delta(old, new)
    except Exception:                                   # never let the cutover diff fail on a reachability hiccup
        rdelta = {"summary": {}, "newly_blocked": [], "newly_reachable": [], "preserved": 0,
                  "inconclusive": 0, "pairs_tested": 0, "subnets_tested": 0, "capped": False}
    n_newly_blocked = len(rdelta.get("newly_blocked") or [])
    n_ecmp_partial = len(_as_list(rdelta.get("ecmp_partial_drop")))

    # Coverage-honest reachability clause -- NEVER an unqualified 'no reachability regressions' (no-silent-caps /
    # not-assessed!=healthy doctrine). It always discloses either 'NOT assessed' or the BOUNDED sample it tested.
    if not rdelta.get("assessed"):
        reach_phrase = ("computed reachability NOT assessed — no routes collected"
                        if (rdelta.get("subnets_total") or 0) == 0 else
                        f"computed reachability NOT assessed — only {rdelta.get('subnets_total')} subnet(s) "
                        "collected, no inter-subnet flow to test")
    else:
        cap = ", capped" if rdelta.get("capped") else ""
        reach_phrase = (f"computed reachability: {n_newly_blocked} of {rdelta.get('pairs_tested', 0)} sampled "
                        f"inter-subnet flow(s) newly blocked (bounded sample: {rdelta.get('subnets_tested', 0)} of "
                        f"{rdelta.get('subnets_total', 0)} subnet(s), one representative host each{cap})")

    # ---- physical cabling delta (the EDA cable-map SSOT, diffed) ----
    # A cable DOWN across the change window is a hard physical regression; '-> unknown' is a coverage
    # event ('no longer observed'), never a down. Pre-cable-map snapshots rehydrate from interfaces.
    try:
        from cisco_toolkit.analyze import cable_map_of_snapshot, compute_cable_map_diff
        cdelta = compute_cable_map_diff(cable_map_of_snapshot(old), cable_map_of_snapshot(new))
    except Exception:                                   # never let the cutover diff fail on the cable pass
        cdelta = {"assessed": False, "added": [], "removed": [], "status_changes": [],
                  "members_changed": [], "summary": {}}
    _cs = cdelta.get("summary") or {}
    n_cables_down = int(_cs.get("n_went_down") or 0)
    n_cables_changed = (int(_cs.get("n_added") or 0) + int(_cs.get("n_removed") or 0)
                        + int(_cs.get("n_members_changed") or 0) + int(_cs.get("n_no_longer_observed") or 0))
    if not cdelta.get("assessed"):
        cable_phrase = ("physical cabling NOT assessed — no CDP/LLDP links in either snapshot "
                        "(NOT a statement that cabling is unchanged)")
    else:
        cable_phrase = (f"physical cabling: {_cs.get('n_added', 0)} cable(s) added, "
                        f"{_cs.get('n_removed', 0)} removed, {n_cables_down} went DOWN, "
                        f"{_cs.get('n_no_longer_observed', 0)} no longer observed")

    # ---- verdict ----
    removed_sw = sorted(set(od) - set(nd), key=_skey)
    adverse_delta = bool(
        n_opened_high or regressed or n_newly_blocked or n_ecmp_partial or n_cables_down
    )
    # Integrity/schema uncertainty dominates the certification verdict.  Keep any adverse
    # observations visible in the note, but never let a real-looking delta imply that the
    # incompatible or incomplete inputs themselves were valid to compare.
    if integrity_failures:
        verdict = "INDETERMINATE"
        observed = []
        if n_opened_high:
            observed.append(f"{n_opened_high} apparent new High/Critical finding(s)")
        if regressed:
            observed.append(f"{len(regressed)} apparent health-band regression(s)")
        if n_newly_blocked:
            observed.append(f"{n_newly_blocked} apparent newly blocked sampled flow(s)")
        if n_ecmp_partial:
            observed.append(f"{n_ecmp_partial} apparent blackholing ECMP leg(s)")
        if n_cables_down:
            observed.append(f"{n_cables_down} apparent cable-down transition(s)")
        observed_note = (
            " Adverse observations that still require investigation: " + "; ".join(observed) + "."
            if observed else ""
        )
        note = (
            f"Delta certification withheld: {len(integrity_failures)} integrity/schema gap(s) make one "
            "or more analyses unavailable. No missing/failed section was interpreted as clean. "
            + "; ".join(integrity_failures)
            + f".{observed_note} {cable_phrase}; {reach_phrase}."
        )
    elif adverse_delta:
        verdict = "REGRESSED"
        bits = []
        if n_opened_high:
            bits.append(f"{n_opened_high} new High/Critical finding(s)")
        if regressed:
            bits.append(f"{len(regressed)} switch(es) dropped a health band")
        if n_ecmp_partial:
            bits.append(f"{n_ecmp_partial} sampled flow(s) have a proven blackholing ECMP leg")
        bits.append(cable_phrase)
        bits.append(reach_phrase)
        note = "; ".join(bits) + ". Investigate before declaring the cutover good."
    elif opened or removed_sw or n_went_dark or newly_bad or n_cables_changed:
        verdict = "REVIEW"
        cov_bits = []
        if n_went_dark:
            cov_bits.append(f"{n_went_dark} switch(es) went dark (lost collection — can't be certified)")
        if newly_bad:
            cov_bits.append(f"{len(newly_bad)} newly-collected switch(es) found Critical/Poor")
        note = (f"{len(opened)} new finding(s); {len(removed_sw)} switch(es) no longer present"
                + ("; " + "; ".join(cov_bits) if cov_bits else "")
                + f"; {cable_phrase}; {reach_phrase}. Confirm these are expected.")
    else:
        verdict = "CLEAN"
        note = (
            "Delta-only observation: no health-band regressions or newly opened findings were observed "
            "in the available comparable analyses; "
            f"{cable_phrase}; {reach_phrase}. This is not a cutover authorization; reconcile the "
            "Pre-Change Certificate and named blind spots."
        )

    def _scn(s):  # SSOT: canonical device count (one source); raw len() only as the pre-brief fallback
        # _as_dict at BOTH levels (the same shape _trend_point's local _d() already guards): a truthy
        # non-dict `executive_brief` -- or a well-formed brief whose inner `scale` is a scalar -- slips
        # past `or {}` and AttributeErrors on the next .get().
        return _as_dict(_as_dict(s.get("executive_brief")).get("scale")).get("n_devices")
    return {
        "switches": {"old": _scn(old) or len(od), "new": _scn(new) or len(nd),
                     "added": sorted(set(nd) - set(od)), "removed": removed_sw},
        # oi/ni are already _as_dict-coerced above; this is the PER-ELEMENT gap -- `interfaces: {"sw1": 5}`
        # reaches len(5). (A null per-host value crashed here too: len(None).)
        "interfaces": {"old": sum(len(_as_dict(v)) for v in oi.values()),
                       "new": sum(len(_as_dict(v)) for v in ni.values())},
        "health": {"regressed": regressed, "improved": improved,
                   "n_regressed": len(regressed), "n_improved": len(improved),
                   "coverage_shifts": coverage_shifts, "n_coverage_shifts": len(coverage_shifts)},
        "findings": {"opened": opened, "resolved": resolved, "n_opened": len(opened),
                     "n_resolved": len(resolved), "n_opened_high": n_opened_high},
        "reachability": rdelta,
        "cabling": cdelta,
        "integrity": {
            "ok": not integrity_failures,
            "failures": integrity_failures,
            "health_comparable": health_comparable,
            "findings_comparable": findings_comparable,
        },
        "provenance": {
            "source_binding": dict(source_binding) if isinstance(source_binding, dict) else {},
            "schema_status": schema,
        },
        "verdict": verdict,
        "verdict_display": ("NO DELTA REGRESSION OBSERVED" if verdict == "CLEAN" else verdict),
        "verdict_scope": "delta_only",
        "verdict_note": note,
    }

def write_diff_workbook(old: dict, new: dict, out_path: str, precert: dict = None, *,
                        source_binding: Optional[dict] = None, schema_status: Any = None) -> None:
    """Write a diff workbook (Summary / Interface Changes / Endpoint Changes /
    SVI Changes) comparing two snapshot_state() dicts. `precert` is an optional precomputed
    Pre-Change Validation Certificate (roadmap C1); when None it is computed here, so the
    'Pre-Change Certificate' sheet is always present.  Exact input hashes and schema-gate status
    supplied by the file-loading caller are rendered into both decision surfaces."""
    old = old if isinstance(old, dict) else {}            # total on a non-dict snapshot (parsed null/[]/scalar)
    new = new if isinstance(new, dict) else {}
    from openpyxl import Workbook
    HF = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    FILL = PatternFill("solid", fgColor=WORKBOOK_NAVY_HEX)
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    DF = Font(name="Calibri", size=10)
    NONE = "\u2205"  # empty marker

    wb = Workbook(); wb.remove(wb.active)
    from cisco_toolkit.excel import harden_workbook
    harden_workbook(wb)   # sanitize control chars in device-derived text -> no IllegalCharacterError abort

    def sheet(title, cols):
        ws = wb.create_sheet(title)
        for c, h in enumerate(cols, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = HF; cell.fill = FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        return ws

    def autofit(ws, ncols):
        for col in range(1, ncols + 1):
            mx = len(str(ws.cell(row=1, column=col).value or ""))
            for row in range(2, ws.max_row + 1):
                v = ws.cell(row=row, column=col).value
                if v is not None: mx = max(mx, len(str(v)))
            ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 60)

    def _ifmap(s):
        """`interfaces` coerced at BOTH levels -- the same read compute_snapshot_delta already routes through
        _as_dict. Re-deriving it here with raw len()/.get() crashed the whole workbook on a trimmed /
        foreign-tool / older-schema snapshot (`interfaces: {"sw1": 5}` -> TypeError at the totals, and the
        string variant `{"sw1": "abc"}` counted 3 phantom interfaces before dying in the sheet loops) -- i.e.
        no diff workbook and no Pre-Change Validation Certificate, at the cutover gate."""
        return {h: {p: _as_dict(d) for p, d in _as_dict(v).items()}
                for h, v in _as_dict(s.get("interfaces")).items()}

    def _dnum(a, b):
        """b - a when both really are numbers. The canonical counts come from the snapshot, so a malformed
        one can carry a string there and a raw subtraction would abort the workbook."""
        ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
        return round(b - a, 1) if ok else ""

    oi, ni = _ifmap(old), _ifmap(new)
    od, nd = _as_dict(old.get("devices")), _as_dict(new.get("devices"))
    delta = compute_snapshot_delta(old, new, source_binding=source_binding,
                                   schema_status=schema_status)   # migration-validation analysis
    # Compute the independent certificate BEFORE the Summary so its coverage verdict can constrain
    # the headline gate.  A clean delta over an unassessed reachability surface is not a PASS.
    from cisco_toolkit.precert import CERT_SHEET_HEADERS, CERT_SHEET_NAME, compute_precert
    if isinstance(precert, dict):
        cert = dict(precert)
        if source_binding and not cert.get("source_binding"):
            cert["source_binding"] = dict(source_binding)
        if schema_status is not None and not cert.get("schema_status"):
            cert["schema_status"] = _schema_status(schema_status)
    else:
        cert = compute_precert(
            old, new, source_hashes=source_binding, schema_status=schema_status)
    rd0 = delta.get("reachability") or {}      # W2 reachability what-if (disclose the bounded sample, never silent)
    cd0 = (delta.get("cabling") or {}).get("summary") or {}   # physical cable delta (EDA cable-map SSOT)

    # Summary (leads with the cutover-validation VERDICT)
    ws = sheet("Summary", ["Metric", "Old", "New", "Delta"])
    added_sw = sorted(set(nd) - set(od), key=_skey); removed_sw = sorted(set(od) - set(nd), key=_skey)
    # SSOT (Law 1): the fleet size and the interface totals are the delta's -- `_scn()` = the canonical
    # executive_brief.scale.n_devices, with len() only as the pre-brief fallback, and the _as_dict-guarded
    # interface count. compute_snapshot_delta (just above) already ran on these SAME two inputs and is what
    # the webapp /api/compare publishes, so a second raw len() here made ONE call render TWO fleet sizes --
    # the AssessHub compare view and the CLI diff workbook disagreeing at the cutover gate.
    o_sw, n_sw = delta["switches"]["old"], delta["switches"]["new"]
    o_if, n_if = delta["interfaces"]["old"], delta["interfaces"]["new"]
    cert_verdict = str(cert.get("verdict") or "INDETERMINATE")
    if delta["verdict"] == "REGRESSED":
        gate_verdict = "REGRESSED"
    elif cert_verdict == "FAIL":
        gate_verdict = "FAIL"
    elif delta["verdict"] == "INDETERMINATE" or cert_verdict == "INDETERMINATE":
        gate_verdict = "INDETERMINATE"
    elif delta["verdict"] == "REVIEW":
        gate_verdict = "REVIEW"
    elif cert_verdict == "CONDITIONAL":
        gate_verdict = "CONDITIONAL"
    else:
        gate_verdict = "PASS"
    gate_note = (
        f"Delta observation: {delta.get('verdict_display', delta['verdict'])}. "
        f"Pre-Change Certificate: {cert_verdict}. {cert.get('verdict_note') or delta['verdict_note']}"
    )
    _VERDICT_FILL = {"PASS": "C6EFCE", "CLEAN": "C6EFCE", "CONDITIONAL": "FFEB9C",
                     "REVIEW": "FFEB9C", "INDETERMINATE": "D9D9D9",
                     "FAIL": "FFC7CE", "REGRESSED": "FFC7CE"}
    metrics = [
        ("CUTOVER GATE VERDICT", "", gate_verdict, gate_note),
        ("DELTA OBSERVATION", "", delta.get("verdict_display", delta["verdict"]), delta["verdict_note"]),
        ("Switches", o_sw, n_sw, _dnum(o_sw, n_sw)),
        # ...added/removed enumerate the COLLECTED devices, which is a narrower set than the canonical
        # count above whenever the estate holds devices that were inventoried but not collected. Labelled,
        # so the two rows cannot be read as one contradictory fact.
        ("Switches added (collected)", "", "", ", ".join(added_sw) or "0"),
        ("Switches removed (collected)", "", "", ", ".join(removed_sw) or "0"),
        ("Interfaces (total)", o_if, n_if, _dnum(o_if, n_if)),
        ("Health bands regressed", "", delta["health"]["n_regressed"],
         ", ".join(r["switch"] for r in delta["health"]["regressed"]) or "0"),
        ("Health bands improved", "", delta["health"]["n_improved"], delta["health"]["n_improved"]),
        ("Findings opened", "", delta["findings"]["n_opened"],
         f"{delta['findings']['n_opened_high']} High/Critical"),
        ("Findings resolved", "", delta["findings"]["n_resolved"], delta["findings"]["n_resolved"]),
        ("Reachability flows newly blocked", "", len(rd0.get("newly_blocked") or []),
         (f"{rd0.get('pairs_tested', 0)} sampled flow(s) across {rd0.get('subnets_tested', 0)} of "
          f"{rd0.get('subnets_total', 0)} subnet(s){' (CAPPED — coverage incomplete)' if rd0.get('capped') else ''}, "
          f"one representative host each; {rd0.get('preserved', 0)} preserved, "
          f"{rd0.get('inconclusive', 0)} inconclusive"
          if rd0.get("assessed") else
          "NOT assessed — no routes collected (this is NOT a statement that reachability is unchanged)")),
        ("Physical cables changed", "", "",
         (f"{cd0.get('n_added', 0)} added, {cd0.get('n_removed', 0)} removed, "
          f"{cd0.get('n_went_down', 0)} went DOWN, {cd0.get('n_no_longer_observed', 0)} no longer observed, "
          f"{cd0.get('n_members_changed', 0)} LAG membership change(s)"
          if (delta.get("cabling") or {}).get("assessed") else
          "NOT assessed — no CDP/LLDP links in either snapshot (NOT a statement that cabling is unchanged)")),
    ]
    r = 2
    for m in metrics:
        for c, v in enumerate(m, 1):
            cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
        if m[0] == "CUTOVER GATE VERDICT":
            vc = ws.cell(row=r, column=3)
            vc.fill = PatternFill("solid", fgColor=_VERDICT_FILL.get(gate_verdict, "FFFFFF"))
            vc.font = Font(name="Calibri", bold=True, size=11)
        r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 70

    # Interface Changes
    ws = sheet("Interface Changes", ["Hostname", "Port", "Change", "Field: Old -> New"])
    r = 2
    for host in sorted(set(oi) | set(ni), key=_skey):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp), key=_skey):
            o, n = op.get(port), npp.get(port)
            if o is None and n is None:
                continue
            if o is None:
                change, deltas = "Added port", []
            elif n is None:
                change, deltas = "Removed port", []
            else:
                change = "Modified"
                deltas = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                          for f in _DIFF_FIELDS if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not deltas:
                    continue
            for c, v in enumerate([host, port, change, " | ".join(deltas)], 1):
                cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 70

    # Endpoint (MAC) Changes
    ws = sheet("Endpoint Changes", ["Hostname", "Port", "Change", "MAC"])
    r = 2
    for host in sorted(set(oi) | set(ni), key=_skey):
        op, npp = oi.get(host, {}), ni.get(host, {})
        for port in sorted(set(op) | set(npp), key=_skey):
            om = _macset((op.get(port) or {}).get("end_host_mac", ""))
            nm = _macset((npp.get(port) or {}).get("end_host_mac", ""))
            for mac in sorted(nm - om):
                for c, v in enumerate([host, port, "MAC appeared", mac], 1):
                    cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
                r += 1
            for mac in sorted(om - nm):
                for c, v in enumerate([host, port, "MAC gone", mac], 1):
                    cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
                r += 1
    autofit(ws, 4)

    # SVI / Gateway Changes
    ws = sheet("SVI Changes", ["Hostname", "SVI", "Change", "Detail"])
    r = 2
    for host in sorted(set(oi) | set(ni), key=_skey):
        op, npp = oi.get(host, {}), ni.get(host, {})
        svis = sorted({p for p in (set(op) | set(npp)) if re.match(r"^Vlan\d+$", p, re.I)})
        for p in svis:
            o, n = op.get(p), npp.get(p)
            if o is None and n is not None:
                ch = "SVI added"
                detail = f"IP {n.get('svi_ip', '') or NONE}, FHRP {n.get('hsrp_behavior', '') or NONE}"
            elif n is None and o is not None:
                ch = "SVI removed"
                detail = f"was IP {o.get('svi_ip', '') or NONE}"
            else:
                diffs = [f"{f}: {o.get(f, '') or NONE} -> {n.get(f, '') or NONE}"
                         for f in ("svi_ip", "hsrp_behavior", "subnet_primary_route")
                         if (o.get(f, "") or "") != (n.get(f, "") or "")]
                if not diffs:
                    continue
                ch, detail = "SVI changed", " | ".join(diffs)
            for c, v in enumerate([host, p, ch, detail], 1):
                cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
            r += 1
    autofit(ws, 4); ws.column_dimensions["D"].width = 60

    # Health Shifts (NEW-V3.23.106) — per-switch health-band change, regressions first
    ws = sheet("Health Shifts", ["Switch", "Direction", "Old band", "New band", "Old score", "New score"])
    r = 2
    for direction, rows in (("REGRESSED", delta["health"]["regressed"]),
                            ("improved", delta["health"]["improved"]),
                            # in/out of 'Insufficient Data' -> labelled by kind (went dark / newly assessed), never
                            # silently folded into 'improved' (audit-4 #5)
                            *(((c["kind"], [c]) for c in delta["health"].get("coverage_shifts", [])))):
        for d in rows:
            vals = [d["switch"], direction, d["old_band"], d["new_band"], d["old_score"], d["new_score"]]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
            if direction == "REGRESSED":
                ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor="FFC7CE")
            r += 1
    if r == 2:
        ws.cell(row=2, column=1, value="No health-band changes between the two snapshots.").font = DF
    autofit(ws, 6)

    # Findings Delta (NEW-V3.23.106) — consolidated punch-list items opened vs resolved by the cutover
    ws = sheet("Findings Delta", ["State", "Severity", "Category", "Devices", "Finding"])
    r = 2
    for state, items in (("OPENED", delta["findings"]["opened"]),
                         ("resolved", delta["findings"]["resolved"])):
        for f in items:
            vals = [state, f.get("severity", ""), f.get("category", ""),
                    _devices_cell(f.get("devices")), f.get("title", "")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
            ws.cell(row=r, column=1).fill = PatternFill(
                "solid", fgColor="FFC7CE" if state == "OPENED" else "C6EFCE")
            r += 1
    if r == 2:
        ws.cell(row=2, column=1, value="No punch-list findings opened or resolved.").font = DF
    autofit(ws, 5); ws.column_dimensions["E"].width = 70

    # Reachability (W2) — computed RIB->FIB flows the change DEFINITIVELY broke (the offline Batfish-peer what-if).
    # Coverage-honest: distinguishes 'tested, no regressions' from 'no routes collected -> not assessed'.
    ws = sheet("Reachability", ["Flow", "Src", "Dst", "Before", "After"])
    r = 2
    for label, fill, items in (("NEWLY BLOCKED", "FFC7CE", rd0.get("newly_blocked") or []),
                               ("newly reachable", "C6EFCE", rd0.get("newly_reachable") or [])):
        for p in items:
            vals = [label, p.get("src", ""), p.get("dst", ""), p.get("old_status", ""), p.get("new_status", "")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
            ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=fill)
            r += 1
    if r == 2:                                            # no regressions to list -> be coverage-honest about WHY
        if rd0.get("assessed"):
            msg = (f"No computed reachability regressions across {rd0.get('pairs_tested', 0)} sampled flow(s) "
                   f"({rd0.get('subnets_tested', 0)} of {rd0.get('subnets_total', 0)} subnet(s), one representative "
                   f"host each{' — CAPPED, coverage incomplete' if rd0.get('capped') else ''}). Bounded sample: a "
                   "regression to an untested host or subnet would not appear here.")
        elif (rd0.get("subnets_total") or 0) == 0:
            msg = "No routes collected — computed reachability NOT assessed (this is NOT 'no regressions')."
        else:
            msg = (f"Only {rd0.get('subnets_total')} subnet(s) collected — no inter-subnet flow to test; "
                   "computed reachability NOT assessed.")
        ws.cell(row=2, column=1, value=msg).font = DF
    autofit(ws, 5); ws.column_dimensions["D"].width = 42; ws.column_dimensions["E"].width = 42

    # Cabling Changes — the EDA cable-map SSOT diffed: physical cables added / removed / op-status
    # flips + LAG membership changes. Coverage-honest: '-> unknown' reads 'no longer observed' (a
    # coverage event, never a down), and a snapshot pair with no CDP/LLDP links reads NOT ASSESSED.
    cd = delta.get("cabling") or {}
    ws = sheet("Cabling Changes", ["Change", "Switch A", "Port A", "Switch B", "Port B", "Status", "Note"])
    cab_rows: list = []
    if not cd.get("assessed"):
        cab_rows.append(("NOT ASSESSED", "", "", "", "", "",
                         "no CDP/LLDP links in either snapshot — NOT a statement that cabling is unchanged"))
    else:
        for c0 in cd.get("status_changes") or []:
            cab_rows.append(("Status changed", c0.get("a", ""), c0.get("a_port", ""), c0.get("b", ""),
                             c0.get("b_port", ""), f"{c0.get('from', '')} -> {c0.get('to', '')}",
                             c0.get("classification", "")))
        for label, items in (("Cable added", cd.get("added") or []), ("Cable removed", cd.get("removed") or [])):
            for c0 in items:
                cab_rows.append((label, c0.get("a", ""), c0.get("a_port", ""), c0.get("b", ""),
                                 c0.get("b_port", ""), c0.get("op_status", ""),
                                 f"port-channel, {len(c0.get('members') or [])} member(s)" if c0.get("is_pc") else ""))
        for m0 in cd.get("members_changed") or []:
            cab_rows.append(("LAG members changed", m0.get("a", ""), m0.get("a_port", ""), m0.get("b", ""),
                             m0.get("b_port", ""), f"{m0.get('old_members', 0)} -> {m0.get('new_members', 0)} member(s)",
                             "a port-channel leg was added or removed"))
        if not cab_rows:
            cab_rows.append(("No changes", "", "", "", "", "",
                             f"{(cd.get('summary') or {}).get('n_unchanged', 0)} cable(s) compared, unchanged"))
    r = 2
    for vals in cab_rows:
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
        if str(vals[5]).endswith("-> down"):
            ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor="FFC7CE")
        r += 1
    autofit(ws, 7); ws.column_dimensions["G"].width = 55

    # Pre-Change Validation Certificate (roadmap C1) — the fib differential packaged as the PPDIOO gate
    # artifact: verdict + every changed flow cited before->after + segmentation invariants + path intents
    # + every NAMED blind spot. Rendered from the certificate dict (the .precert.json SSOT); computed here
    # when the caller did not pass one, so the sheet is always present.
    cf = cert.get("flows") or {}
    _CERT_FILL = {"PASS": "C6EFCE", "CONDITIONAL": "FFEB9C", "FAIL": "FFC7CE", "INDETERMINATE": "D9D9D9"}
    stamps = cert.get("stamps") or {}
    if cf.get("assessed"):
        cover = (f"{cf.get('preserved', 0)} preserved, {cf.get('both_unreachable', 0)} unreachable both sides, "
                 f"{len(cf.get('changed') or [])} changed, {len(cf.get('inconclusive') or [])} inconclusive "
                 f"(bounded sample: {cf.get('subnets_tested', 0)} of {cf.get('subnets_total', 0)} subnet(s), one "
                 f"representative host each{', CAPPED — coverage incomplete' if cf.get('capped') else ''})")
    else:
        cover = "computed reachability NOT assessed (this is NOT a statement that reachability is unchanged)"
    cert_rows: list = [
        ("VERDICT", "pre-change validation certificate",
         (stamps.get("before") or {}).get("generated_at", ""), (stamps.get("after") or {}).get("generated_at", ""),
         cert.get("verdict", ""), cert.get("verdict_note", "")),
        ("Flows", "coverage", "", "", f"{cf.get('pairs_tested', 0)} flow(s) tested", cover),
    ]
    for f0 in (cf.get("changed") or []):
        cert_rows.append(("Flows", f"{f0.get('src')} -> {f0.get('dst')}", f0.get("before", ""), f0.get("after", ""),
                          "NEWLY BLOCKED" if f0.get("regression") else "newly reachable", ""))
    for f0 in (cf.get("inconclusive") or []):
        cert_rows.append(("Flows", f"{f0.get('src')} -> {f0.get('dst')}", "", "", "INCONCLUSIVE",
                          f0.get("reason", "")))
    for s0 in (cert.get("segmentation") or []):
        held = s0.get("held")
        cert_rows.append(("Segmentation", s0.get("invariant", ""), "", "",
                          "HELD" if held is True else ("VIOLATED" if held is False else "NOT EVALUABLE"),
                          s0.get("evidence", "")))
    for i0 in (cert.get("intents") or []):
        cert_rows.append(("Intent", f"{i0.get('id')} (expect {i0.get('expect')})",
                          i0.get("old_verdict", ""), i0.get("new_verdict", ""),
                          "REGRESSED" if i0.get("regressed") else
                          ("coverage lost" if i0.get("coverage_lost") else str(i0.get("new_verdict", ""))),
                          f"{i0.get('old_status')} -> {i0.get('new_status')}"))
    for b0 in (cert.get("blind_spots") or []):
        cert_rows.append(("Blind spot", b0, "", "", "OPEN", ""))
    for g0 in (cert.get("gate_failures") or []):
        cert_rows.append(("Gate failure", g0, "", "", "BLOCKING", "Do not proceed"))
    if not (cert.get("blind_spots") or []):
        cert_rows.append(("Blind spot", "none open", "", "", "", ""))
    binding = cert.get("source_binding") if isinstance(cert.get("source_binding"), dict) else {}
    for side in ("before", "after"):
        if binding.get(side):
            cert_rows.append(("Provenance", f"{side} input SHA-256", "", "",
                              "BOUND", str(binding.get(side))))
    schema_binding = cert.get("schema_status") if isinstance(cert.get("schema_status"), dict) else {}
    if schema_binding:
        cert_rows.append(("Provenance", "schema compatibility", "", "",
                          str(schema_binding.get("status") or "unverifiable").upper(),
                          str(schema_binding.get("message") or "")
                          + (" (explicit override recorded)" if schema_binding.get("override") else "")))
    _ROW_FILL = {"NEWLY BLOCKED": "FFC7CE", "newly reachable": "C6EFCE", "VIOLATED": "FFC7CE",
                 "REGRESSED": "FFC7CE", "INCONCLUSIVE": "D9D9D9", "NOT EVALUABLE": "D9D9D9", "OPEN": "FFEB9C"}
    _ROW_FILL["BLOCKING"] = "FFC7CE"
    ws = sheet(CERT_SHEET_NAME, list(CERT_SHEET_HEADERS))
    r = 2
    for vals in cert_rows:
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
        if vals[0] == "VERDICT":
            vc = ws.cell(row=r, column=5)
            vc.fill = PatternFill("solid", fgColor=_CERT_FILL.get(str(vals[4]), "FFFFFF"))
            vc.font = Font(name="Calibri", bold=True, size=11)
        elif str(vals[4]) in _ROW_FILL:
            ws.cell(row=r, column=5).fill = PatternFill("solid", fgColor=_ROW_FILL[str(vals[4])])
        r += 1
    autofit(ws, 6); ws.column_dimensions["B"].width = 46; ws.column_dimensions["F"].width = 70

    wb.save(out_path)


# -----------------------------------------------------------------------------
# Migration CAMPAIGN trend (NEW-V3.23.145). Where compute_snapshot_delta diffs a PAIR (pre/post a single
# cutover), the campaign tracker ingests a SERIES of collections taken across the whole migration and shows
# the trajectory: is the network actually getting healthier wave by wave? It extracts the headline metrics
# per collection (avg health, band mix, punch-list size + Critical/High count, NOT-READY groups,
# Past-LDoS),
# computes the first->last trajectory per metric + an overall IMPROVING/MIXED/REGRESSING verdict, and reuses
# compute_snapshot_delta for the per-step findings burndown (opened vs resolved). Pure read of N snapshot
# dicts; tolerant of older snapshots that lack a metric -- it is omitted from the trajectory, never scored as
# a zero, and if it was comparable at ONE end of the campaign only, its loss is disclosed in the verdict note.
# -----------------------------------------------------------------------------
def _trend_point(snap: dict) -> dict:
    """Headline metrics for one snapshot in the campaign timeline."""
    # Tolerant of a malformed --trend/--compare snapshot: a wrong-typed health_scores (a dict, not the
    # expected list-of-dicts) would iterate its KEYS (str), and `str.get` raises AttributeError -> the whole
    # trend workbook aborts (CLI --trend is unwrapped). Coerce to a list of dicts up front; a non-dict row
    # can't reach the `.get` calls below.
    # COVERAGE HONESTY: `have_*` records whether the section was actually PRESENT (a usable list), so an
    # absent one abstains with "" instead of tallying to a hard 0. A partial upload, an older schema, or a
    # failed analysis phase otherwise scored identically to a clean fleet -- and, being a fall in every
    # counter, read as a campaign IMPROVING to a green "CAMPAIGN VERDICT". avg_health and past_ldos in this
    # same dict already abstained; the idiom was simply applied to 2 of the 6 metrics.
    _hs = snap.get("health_scores")
    have_hs = isinstance(_hs, list)
    hs = [r for r in _hs if isinstance(r, dict)] if have_hs else []
    # _renderable_num, not a bare isinstance((int, float)): that admitted the two numeric values a JSON
    # snapshot can carry but arithmetic cannot survive -- an unbounded-precision int literal
    # (`sum(scores)/len(scores)` -> "integer division result too large for a float", aborting the whole
    # --trend workbook) and the bare `Infinity`/`NaN` json.loads accepts (which would render an average
    # of inf/nan into the campaign deck).
    scores = [r.get("score") for r in hs if _renderable_num(r.get("score"))]
    bands: Dict[str, int] = {}
    for r in hs:
        bands[str(r.get("band", ""))] = bands.get(str(r.get("band", "")), 0) + 1
    _pl = snap.get("punchlist")
    have_pl = isinstance(_pl, list)
    pl = [f for f in _pl if isinstance(f, dict)] if have_pl else []   # same list-of-dicts guard as health_scores
    readiness = {"READY": 0, "CAUTION": 0, "NOT READY": 0}
    _mr = snap.get("migration_readiness")
    have_mr = isinstance(_mr, list)
    for r in (_mr if have_mr else []):
        rd = _hkey(r.get("readiness")) if isinstance(r, dict) else None
        if rd in readiness:                       # _hkey: an unhashable label must not raise on `in`
            readiness[rd] += 1
    # isinstance-guard (not `or {}`): a TRUTHY non-dict section/subsection (a list/str/int in a malformed
    # --trend/--compare upload) slips past `or {}` and crashes the .get() below -> 500s the unwrapped /trend
    # endpoint and aborts the CLI --trend workbook. Same truthy-non-dict class the deliverables already guard.
    def _d(v):
        return v if isinstance(v, dict) else {}
    lr = _d(_d(snap.get("lifecycle_risk")).get("summary"))
    _eb = _d(snap.get("executive_brief"))
    _scale = _d(_eb.get("scale"))
    _posture = _d(_eb.get("posture"))
    avg = _posture.get("avg_health")
    if avg is None and scores:
        avg = round(sum(scores) / len(scores), 1)
    # str() (not `or ""`): `generated_at` is a timestamp STRING by contract, but a truthy non-str survives
    # `or ""` and the ts[:10] slice below then raises (`5[:10]` -> TypeError) -- or, for a list, silently
    # returns a LIST into the timeline's 'date' column. The slicing variant of the same guard gap.
    ts = str(snap.get("generated_at") or "")
    integrity = _analysis_integrity(
        snap, ("health_scores", "punchlist", "migration_readiness", "lifecycle_risk"))
    return {
        "date": ts[:10], "generated_at": ts, "version": snap.get("script_version", ""),
        # SSOT: prefer the engine's canonical scale / posture; the local len()/band-tally is a fallback only.
        "n_switches": _scale.get("n_devices") if _scale.get("n_devices") is not None else len(_d(snap.get("devices"))),
        "avg_health": avg if avg is not None else "",
        # Each falls back to its raw tally ONLY when that section was collected; otherwise "" (abstain),
        # exactly like avg_health/past_ldos below. "Not observed" must never render as an observed zero.
        "n_critical": _posture.get("n_critical") if _posture.get("n_critical") is not None else (
            bands.get("Critical", 0) if have_hs else ""),
        "n_punchlist": len(pl) if have_pl else "",
        "n_crit_high": sum(1 for f in pl if f.get("severity") in ("Critical", "High")) if have_pl else "",
        "n_not_ready": readiness["NOT READY"] if have_mr else "",
        # "Past end-of-support" = Past-LDoS — the migration-critical date-band count the
        # brief/deck/explorer/workbook all headline. NOT Past-EoS (end-of-SALE while LDoS remains future;
        # neither band proves entitlement): reading
        # n_past_eos here showed 0 while 152 boxes were past support (the EoS/LDoS silent-drop class).
        # A count over PARTIAL coverage must not be trended as if it were complete. `past_ldos` is
        # lower-is-better in _TREND_METRICS, so a fleet whose platforms lack an exact EoX match or
        # complete retained source/date authority reports 0 and scores as the BEST possible value —
        # an un-assessed campaign step
        # reads as an improvement over a fully-assessed earlier one. That is absence converted into
        # a positive signal, which is worse than absence rendered as neutral.
        #
        # `""` is this dict's existing "not available" convention (see n_punchlist / n_not_ready
        # above), and the trajectory skips a metric that is missing on either side rather than
        # comparing against it. So an incomplete step drops out of THIS metric only; every other
        # metric on that snapshot still trends. (handoff §7.25)
        "past_ldos": ("" if lr.get("n_unknown") else lr.get("n_past_ldos", "")) if lr else "",
        "integrity_ok": integrity["ok"],
        "integrity_failures": integrity["failures"],
    }


# (metric label, timeline key, lower-is-better) for the trajectory + the timeline columns.
_TREND_METRICS = (("Avg health / 100", "avg_health", False),
                  ("Critical-band switches", "n_critical", True),
                  ("Punch-list items", "n_punchlist", True),
                  ("Critical/High findings", "n_crit_high", True),
                  ("NOT READY groups", "n_not_ready", True),
                  ("Past end-of-support", "past_ldos", True))


def compute_campaign_trend(snapshots: List[dict], *, source_bindings: Optional[list] = None,
                           schema_status: Any = None) -> dict:
    """Trajectory of a migration campaign across a SERIES of snapshots. Returns
    {timeline, steps, trajectory, verdict, verdict_note}; degrades gracefully when a metric is absent.
    A collection with a failed/missing core analysis makes the campaign verdict INDETERMINATE rather
    than allowing the remaining counters to manufacture an improvement."""
    snaps = list(snapshots or [])
    timeline = [dict(_trend_point(s), collection=f"C{i + 1}") for i, s in enumerate(snaps)]
    schema = _schema_status(schema_status)
    failed_collections = [
        {"collection": pt["collection"], "failures": list(pt.get("integrity_failures") or [])}
        for pt in timeline if not pt.get("integrity_ok")
    ]
    if schema and schema.get("status") not in ("", "ok"):
        failed_collections.append({
            "collection": "series",
            "failures": [
                f"schema compatibility {schema.get('status')}: "
                f"{schema.get('message') or 'cross-input compatibility was not proven'}"
                + (" (explicit override recorded)" if schema.get("override") else "")
            ],
        })

    steps: List[dict] = []
    for i in range(len(snaps) - 1):
        pair_binding = None
        if isinstance(source_bindings, list) and i + 1 < len(source_bindings):
            pair_binding = {"before": source_bindings[i], "after": source_bindings[i + 1]}
        d = compute_snapshot_delta(snaps[i], snaps[i + 1],
                                   source_binding=pair_binding, schema_status=schema)
        steps.append({
            "from": timeline[i]["collection"], "to": timeline[i + 1]["collection"],
            "from_date": timeline[i]["date"], "to_date": timeline[i + 1]["date"],
            "opened": d["findings"]["n_opened"], "opened_high": d["findings"]["n_opened_high"],
            "resolved": d["findings"]["n_resolved"], "net": d["findings"]["n_opened"] - d["findings"]["n_resolved"],
            "regressed": d["health"]["n_regressed"], "improved": d["health"]["n_improved"],
            "verdict": d["verdict"],
        })

    trajectory: List[dict] = []
    lost: List[str] = []
    never: List[str] = []
    verdict, note = "INSUFFICIENT", "Need at least two collections to show a trend."
    if len(timeline) >= 2:
        first, last = timeline[0], timeline[-1]
        # Metrics whose EVIDENCE was collected in one endpoint of the campaign and not the other. Dropping
        # them from the trajectory is right (they are not comparable) but doing it SILENTLY is the same
        # survivorship trap as a device dropping out: the surviving metrics then set a verdict over a
        # narrower estate than the reader assumes. Disclosed below, and (like a dark device) a clean
        # IMPROVING/FLAT is downgraded.
        #
        # BOTH ends abstaining was the remaining silence, and it is the WORSE one. "Never part of this
        # campaign's evidence" was an assumption, not an observation: `_trend_point` yields a non-numeric
        # value for a metric whose analysis FAILED or was never collected, so a campaign in which the
        # lifecycle/EoL pass fell over at every collection dropped that metric out of the trajectory
        # entirely -- measured, both ends all-Unknown gives verdict FLAT with the lifecycle row simply
        # absent and no NOT-COMPARABLE line. A reader cannot tell "we looked and found nothing" from
        # "we never looked", and a count of 0 that means NOT MEASURED must not read as nothing wrong.
        # Disclosed separately from `lost` because the actions differ: one endpoint missing is usually a
        # collection gap in that run, both missing means the metric was never measured in this campaign
        # at all. It does NOT downgrade the verdict -- there is no evidence in either direction to
        # downgrade on -- it is stated.
        for metric, key, good_down in _TREND_METRICS:
            a, b = first.get(key), last.get(key)
            ok_a, ok_b = isinstance(a, (int, float)), isinstance(b, (int, float))
            if not ok_a or not ok_b:
                (lost if ok_a != ok_b else never).append(metric)
                continue
            delta = b - a
            direction = "flat" if delta == 0 else (
                "improving" if ((delta < 0) if good_down else (delta > 0)) else "worsening")
            trajectory.append({"metric": metric, "first": a, "last": b,
                               "delta": round(delta, 1), "direction": direction})
        better = sum(1 for r in trajectory if r["direction"] == "improving")
        worse = sum(1 for r in trajectory if r["direction"] == "worsening")
        # Devices that went DARK across the campaign (present in an earlier collection, absent later). A rising
        # avg-health is partly SURVIVORSHIP when an unhealthy device drops out of the average, so a campaign that
        # lost devices cannot read a clean IMPROVING without disclosing them (audit-2 #4 false-health).
        gone: set = set()

        def _bands(s):
            return {str(r.get("switch")): str(r.get("band", "")) for r in _as_list(s.get("health_scores"))
                    if isinstance(r, dict)}
        for i in range(len(snaps) - 1):
            # _as_dict, not `or {}`: set(5) raises, and set("sw1") SUCCEEDS on a string -- yielding the
            # CHARACTERS, so the went-dark scan would report three phantom devices gone and downgrade the
            # verdict on evidence that does not exist. Both halves of the same guard gap.
            gone |= set(_as_dict(snaps[i].get("devices"))) - set(_as_dict(snaps[i + 1].get("devices")))
            # the engine never DROPS an uncollected device -- it keeps it as an 'Insufficient Data' STUB in
            # `devices`, so the set-difference above misses a previously-collected switch that went dark; detect
            # the band transition real-band -> 'Insufficient Data' too, else a campaign that loses its worst
            # collected switches reads a survivorship-biased IMPROVING (audit-5 #9).
            b0, b1 = _bands(snaps[i]), _bands(snaps[i + 1])
            for sw, band in b0.items():
                if band and band != "Insufficient Data" and b1.get(sw) == "Insufficient Data":
                    gone.add(sw)
        n_gone = len(gone)
        if trajectory:                                    # comparable metrics exist -> a real verdict
            if better == 0 and worse == 0:
                verdict = "FLAT"
            elif better > worse:
                verdict = "IMPROVING"
            elif worse > better:
                verdict = "REGRESSING"
            else:
                verdict = "MIXED"
            if n_gone and verdict in ("IMPROVING", "FLAT"):
                verdict = "MIXED"                         # devices went dark -> not a clean improvement
            if lost and verdict in ("IMPROVING", "FLAT"):
                verdict = "MIXED"                         # lost evidence -> not a clean improvement either
        hr = next((r for r in trajectory if r["metric"].startswith("Avg health")), None)
        cr = next((r for r in trajectory if r["metric"].startswith("Critical/High")), None)
        parts = [f"Across {len(timeline)} collections: {better} metric(s) improving, {worse} worsening."]
        if hr:
            parts.append(f"Avg health {hr['first']}→{hr['last']}.")
        if cr:
            parts.append(f"Critical/High findings {cr['first']}→{cr['last']}.")
        if n_gone:
            parts.append(f"{n_gone} device(s) went DARK (present then absent) -- the health trajectory may "
                         "be survivorship-biased; confirm these are planned decommissions, not failures.")
        if lost:
            parts.append(f"NOT COMPARABLE: {len(lost)} metric(s) lost their evidence between the first and "
                         f"last collection ({', '.join(lost)}) -- excluded from the verdict, and NOT a "
                         "statement that they are clean.")
        if never:
            parts.append(f"NOT COMPARABLE: {len(never)} metric(s) were never measured at EITHER end of "
                         f"this campaign ({', '.join(never)}) -- absent from the trajectory above because "
                         "there is no evidence, NOT because there is nothing to report.")
        note = " ".join(parts).strip()

        if failed_collections:
            verdict = "INDETERMINATE"
            detail = "; ".join(
                f"{row['collection']}: {', '.join(str(x) for x in row['failures'])}"
                for row in failed_collections)
            note = (
                f"Campaign certification withheld because {len(failed_collections)} collection/schema "
                f"integrity record(s) are not trustworthy. The trajectory remains visible only as a "
                f"partial observation and is not an improvement claim. {detail}. {note}"
            ).strip()

    return {"timeline": timeline, "steps": steps, "trajectory": trajectory,
            # Machine-readable twin of the two NOT-COMPARABLE sentences in verdict_note, so a
            # renderer can show the gap as a row rather than having to parse prose. `lost` = the
            # evidence existed at one end only; `never_measured` = neither end had it, which is
            # NOT the same as a clean zero.
            "not_comparable": {"lost": list(lost), "never_measured": list(never)},
            "integrity": {"ok": not failed_collections, "failures": failed_collections},
            "provenance": {
                "source_bindings": list(source_bindings) if isinstance(source_bindings, list) else [],
                "schema_status": schema,
            },
            "verdict": verdict, "verdict_note": note}


def write_campaign_workbook(snapshots: List[dict], out_path: str, *,
                            source_bindings: Optional[list] = None, schema_status: Any = None) -> None:
    """Write a migration-campaign trend workbook (Campaign Summary verdict + per-metric trajectory /
    Timeline w/ a trajectory line chart / Burndown of findings opened-vs-resolved per step) from a SERIES
    of snapshot_state() dicts."""
    from openpyxl import Workbook
    HF = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    FILL = PatternFill("solid", fgColor=WORKBOOK_NAVY_HEX)
    AL = Alignment(horizontal="left", vertical="top", wrap_text=True)
    CEN = Alignment(horizontal="center", vertical="center", wrap_text=True)
    DF = Font(name="Calibri", size=10)

    trend = compute_campaign_trend(
        snapshots, source_bindings=source_bindings, schema_status=schema_status)
    wb = Workbook(); wb.remove(wb.active)
    from cisco_toolkit.excel import harden_workbook
    harden_workbook(wb)   # sanitize control chars in device-derived text -> no IllegalCharacterError abort

    def sheet(title, cols):
        ws = wb.create_sheet(title)
        for c, h in enumerate(cols, 1):
            cell = ws.cell(row=1, column=c, value=h); cell.font = HF; cell.fill = FILL; cell.alignment = CEN
        ws.freeze_panes = "A2"
        return ws

    def autofit(ws, ncols):
        for col in range(1, ncols + 1):
            mx = len(str(ws.cell(row=1, column=col).value or ""))
            for row in range(2, ws.max_row + 1):
                v = ws.cell(row=row, column=col).value
                if v is not None:
                    mx = max(mx, len(str(v)))
            ws.column_dimensions[get_column_letter(col)].width = min(max(mx + 2, 12), 60)

    _DIR_FILL = {"improving": "C6EFCE", "worsening": "FFC7CE", "flat": "FFEB9C"}
    _VERDICT_FILL = {"IMPROVING": "C6EFCE", "MIXED": "FFEB9C", "FLAT": "DDEBF7",
                     "REGRESSING": "FFC7CE", "INDETERMINATE": "D9D9D9",
                     "INSUFFICIENT": "EFEFEF"}

    # ---- Campaign Summary (leads with the trajectory verdict) ----
    ws = sheet("Campaign Summary", ["Metric", "First", "Last", "Delta", "Trajectory"])
    vc = ws.cell(row=2, column=1, value="CAMPAIGN VERDICT"); vc.font = Font(name="Calibri", bold=True, size=11)
    vv = ws.cell(row=2, column=2, value=_cv(trend["verdict"]))
    vv.font = Font(name="Calibri", bold=True, size=11)
    vv.fill = PatternFill("solid", fgColor=_VERDICT_FILL.get(trend["verdict"], "FFFFFF"))
    ws.cell(row=2, column=3, value=_cv(trend["verdict_note"])).alignment = AL
    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=5)
    r = 4
    for t in trend["trajectory"]:
        for c, v in enumerate([t["metric"], t["first"], t["last"], t["delta"], t["direction"]], 1):
            cell = ws.cell(row=r, column=c, value=_cv(v)); cell.font = DF; cell.alignment = AL
        ws.cell(row=r, column=5).fill = PatternFill("solid", fgColor=_DIR_FILL.get(t["direction"], "FFFFFF"))
        r += 1
    if not trend["trajectory"]:
        ws.cell(row=4, column=1, value="Not enough comparable metrics across the snapshots.").font = DF
    prov = trend.get("provenance") or {}
    binds = prov.get("source_bindings") if isinstance(prov.get("source_bindings"), list) else []
    if binds:
        r += 1
        ws.cell(row=r, column=1, value="INPUT SHA-256 BINDINGS").font = Font(name="Calibri", bold=True, size=10)
        ws.cell(row=r, column=2, value=_cv("; ".join(
            f"C{i + 1}={str(v)}" for i, v in enumerate(binds)))).alignment = AL
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
    schema = prov.get("schema_status") if isinstance(prov.get("schema_status"), dict) else {}
    if schema:
        r += 1
        ws.cell(row=r, column=1, value="SCHEMA COMPATIBILITY").font = Font(name="Calibri", bold=True, size=10)
        ws.cell(row=r, column=2, value=_cv(
            f"{str(schema.get('status') or 'unverifiable').upper()}: {schema.get('message') or ''}"
            + (" (explicit override recorded)" if schema.get("override") else ""))).alignment = AL
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
    autofit(ws, 5); ws.column_dimensions["A"].width = 26

    # ---- Timeline (one row per collection) + a trajectory line chart ----
    cols = ["Collection", "Date", "Version", "Switches", "Avg Health", "Critical",
            "Punch-list", "Crit/High", "NOT READY", "Past end-of-support"]
    ws = sheet("Timeline", cols)
    keys = ["collection", "date", "version", "n_switches", "avg_health", "n_critical",
            "n_punchlist", "n_crit_high", "n_not_ready", "past_ldos"]
    for i, pt in enumerate(trend["timeline"], start=2):
        for c, k in enumerate(keys, 1):
            cell = ws.cell(row=i, column=c, value=_cv(pt.get(k, ""))); cell.font = DF
            cell.alignment = CEN if c >= 4 else AL
    autofit(ws, len(cols))
    if len(trend["timeline"]) >= 2:
        try:
            from openpyxl.chart import LineChart, Reference
            n = len(trend["timeline"])
            chart = LineChart(); chart.title = "Migration trajectory"; chart.style = 12
            chart.y_axis.title = "count / score"; chart.x_axis.title = "collection"; chart.height = 8; chart.width = 16
            for col in (5, 8, 7):   # Avg Health, Crit/High, Punch-list
                chart.add_data(Reference(ws, min_col=col, min_row=1, max_row=1 + n), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=1 + n))
            ws.add_chart(chart, get_column_letter(len(cols) + 2) + "2")
        except Exception as e:
            logger.warning(f"  Campaign trend chart skipped: {e}")

    # ---- Burndown (findings opened vs resolved per consecutive step) ----
    ws = sheet("Burndown", ["Step", "Opened", "Opened High/Crit", "Resolved", "Net", "Health regressed",
                            "Health improved", "Step verdict"])
    for i, st in enumerate(trend["steps"], start=2):
        vals = [f"{st['from']} → {st['to']}", st["opened"], st["opened_high"], st["resolved"],
                st["net"], st["regressed"], st["improved"], st["verdict"]]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=_cv(v)); cell.font = DF
            cell.alignment = CEN if 2 <= c <= 7 else AL
        nf = ws.cell(row=i, column=5)
        nf.fill = PatternFill("solid", fgColor="FFC7CE" if (st["net"] or 0) > 0 else "C6EFCE")
    if not trend["steps"]:
        ws.cell(row=2, column=1, value="Need at least two snapshots for a burndown.").font = DF
    autofit(ws, 8)

    wb.save(out_path)
    logger.info(f"[OK] Campaign trend: {trend['verdict']} across {len(trend['timeline'])} collections")


def snapshot_state(all_interfaces: Dict[str, Dict[str, InterfaceData]],
                   all_device_physical: List[DevicePhysical]) -> dict:
    import dataclasses
    return {
        "schema": "collect_parse_snapshot/1",
        "script_version": f"V{__version__}",   # NEW-V3.23.8 (M2): was hard-coded "V3.23.0"
        "generated_at": datetime.now().isoformat(),
        "devices": {dp.hostname: dataclasses.asdict(dp) for dp in all_device_physical},
        "interfaces": {host: {port: dataclasses.asdict(d) for port, d in ifaces.items()}
                       for host, ifaces in all_interfaces.items()},
    }


def sparsify_interfaces(snap: dict) -> dict:
    """Return a SHALLOW copy of `snap` whose `interfaces` subtree drops every field equal to its
    empty default (Tier-3 #14 Phase-2). InterfaceData fields default to '' except the positive
    ``run_config_observed`` boolean, so dropping '' and that field's False value is lossless --
    InterfaceData.from_sparse restores omitted defaults on read
    (~70% of the interface field-cells are '' on a real fleet). Confined to `interfaces`: `devices`
    (DevicePhysical) has non-'' defaults and stays dense. Applied ONLY to the on-disk snapshot; the
    in-memory snap_dict every in-process consumer reads is left untouched, so this changes nothing
    about the pipeline's behaviour -- only the persisted file's size."""
    ifaces = snap.get("interfaces")
    if not isinstance(ifaces, dict):
        return snap
    sparse = {host: {port: {k: v for k, v in rec.items()
                            if v != "" and not (k == "run_config_observed" and v is False)}
                     for port, rec in ports.items() if isinstance(rec, dict)}
              for host, ports in ifaces.items() if isinstance(ports, dict)}
    return {**snap, "interfaces": sparse}


# -----------------------------------------------------------------------------
# NEW-V3.23.90: shrink the snapshot copy EMBEDDED in the single-file explorer.
# The on-disk snapshot.json stays full-fidelity (it is the data contract and the
# `--compare` input); this only trims the in-page payload, which on a real fleet
# (the 254-device Meridian scan embedded a 52 MB blob) is dominated by two things the
# explorer never renders verbatim:
#   * interfaces  - hundreds of ports/device, ~50 fields each, most empty strings.
#     The explorer reads every interface field defensively (`d.x||""`, `d.x&&...`,
#     `(d.x||"").trim()`), so an ABSENT key is indistinguishable from an empty one
#     -> dropping empty/placeholder field VALUES is display-neutral. The port entry
#     itself is always kept so buildModel's `Object.keys(ifaces[host])` is unchanged.
#   * physical_health - tens of thousands of Info/OK rows; the sole consumer
#     (deviceIntelSection) filters severity to non-Info/non-OK, so they are dead weight.
# Everything else (already aggregated per-host in analyze, V3.23.90) passes through.
# -----------------------------------------------------------------------------
_EMBED_DROP_VALUES: tuple = ("", None, [], {}, "--")


def _slim_ports(ports) -> dict:
    """One host's {port: record} map with empty/placeholder field VALUES dropped.

    isinstance-coerced at BOTH levels, exactly as sparsify_interfaces already does: `interfaces` itself is
    isinstance-guarded by the caller, but the PER-ELEMENT layer was not -- a truthy non-dict per-host map
    (`interfaces: {"sw1": 5}`) or port record (`{"Gi1/0/1": 5}`) survives `... or {}` and AttributeErrors on
    .items(). On a stored AssessHub upload that is a permanent 500 for GET /api/snapshots/{id}/explorer,
    which has no try wrapper.

    Behaviour-preserving: a FALSY map/record still degrades to {} exactly as `(x or {})` did, and the port
    ENTRY is still always kept, so the explorer's `Object.keys(ifaces[host])` is unchanged."""
    if not isinstance(ports, dict):
        return {}
    return {port: ({k: v for k, v in rec.items() if v not in _EMBED_DROP_VALUES}
                   if isinstance(rec, dict) else {})
            for port, rec in ports.items()}


def _script_safe_json(value) -> str:
    """``json.dumps`` hardened for the HTML ``<script>`` DATA context — which is NOT the JS string
    context ``json.dumps`` alone is correct for.

    Inside ``<script>...</script>`` the HTML tokenizer runs before the JS parser, so a few byte
    sequences change what the browser considers script text no matter how well-formed the JS is:

      * ``</script`` closes the element early — the classic break-out.
      * ``<!--`` enters script-data-escaped state, and a following ``<script`` enters
        script-data-double-escaped, in which the template's own ``</script>`` no longer closes the
        element. Neither sequence contains ``</``, so the old ``.replace("</", "<\\\\/")`` missed both.

    Escaping EVERY ``<`` as ``\\u003c`` makes all three transitions inexpressible, and is lossless:
    ``<`` only ever occurs inside JSON string values here, and ``\\u003c`` is a valid escape in both
    JSON and JS that parses back to ``<``. U+2028/U+2029 are escaped too because ``ensure_ascii=False``
    would otherwise emit them raw, and they are JS line terminators inside a string literal.

    This is the ONE encoder for anything interpolated into the explorer's script block; the defect it
    replaces came from the payload and the label being hardened differently.
    """
    out = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return (out.replace("<", "\\u003c")
               .replace("\u2028", "\\u2028")
               .replace("\u2029", "\\u2029"))


def _slim_for_embed(snap_dict: dict) -> dict:
    """Return a renderer-scoped, size-reduced copy of the snapshot for embedding in the
    explorer HTML. Pure (input not mutated); see the block comment above for why each
    transform is safe. Defensive: tolerates missing/oddly-typed sections."""
    out = dict(snap_dict)
    # Traffic Assurance has no dedicated explorer renderer.  Embedding either its governed results or the
    # supporting custody receipt would create a silent, unused projection with no UI contract; withhold both
    # until that renderer exists and can preserve the snapshot's exact verdict/custody semantics.
    out.pop("traffic_assurance", None)
    out.pop("traffic_evidence_custody", None)
    intf = snap_dict.get("interfaces")
    if isinstance(intf, dict):
        out["interfaces"] = {host: _slim_ports(ports) for host, ports in intf.items()}
    ph = snap_dict.get("physical_health")
    if isinstance(ph, list):
        out["physical_health"] = [
            r for r in ph
            if not (isinstance(r, dict) and r.get("severity") in ("Info", "OK", None))]
    return out


# -----------------------------------------------------------------------------
# NEW-V3.17: HTML consolidation. Bake the live snapshot into a copy of the
# read-only Blast-Radius Explorer template so one run yields both the workbook
# and a ready-to-open, air-gapped topology explorer (no second tool, no manual
# snapshot load). Pure stdlib (os + json); no new imports.
# -----------------------------------------------------------------------------
def write_html_explorer(output_path: str, snap_dict: dict, label: str) -> None:
    """
    Emit a self-contained Blast-Radius Explorer with the live topology embedded.

    Reads 'blast_radius_explorer.html' from inside the package (with a fallback to the legacy repo-root
    location), replaces its demo bootstrap with the embedded snapshot, and writes the patched
    single-file HTML to output_path.

    The template boots on a demo via the LAST statement in its <script>:
        load(demoSnapshot(),"DEMO TOPOLOGY",false);
    That exact text also appears earlier as the demo button's onclick handler, so a
    naive str.replace() (which replaces every occurrence) would corrupt the button -
    it would inject a `const` declaration into an arrow-function body and break all
    JS on the page. We therefore replace ONLY the final occurrence (the real
    bootstrap) via rpartition(), leaving the demo button intact as a one-click way
    back to the sample topology.

    Safety / robustness:
      * Missing template -> warn and skip (never crash a run whose workbook already saved).
      * Bootstrap line absent (template changed) -> warn and skip.
      * Snapshot is minified (separators=(',',':')) to keep the embedded payload small.
      * BOTH the payload and the label are emitted via ``_script_safe_json`` -- see there. Neither
        device-derived text nor the caller-supplied label can break out of the <script> block.
    """
    # The explorer template ships INSIDE the package (cisco_toolkit/blast_radius_explorer.html), so it is
    # present in a built wheel and resolves the same whether the package is run from a checkout or a
    # pip install. Fall back to the legacy repo-root location for any older layout that still keeps it there.
    _here = os.path.dirname(os.path.abspath(__file__))
    template = os.path.join(_here, "blast_radius_explorer.html")
    if not os.path.isfile(template):
        template = os.path.join(os.path.dirname(_here), "blast_radius_explorer.html")  # legacy repo-root
    if not os.path.isfile(template):
        logger.warning(f"  HTML Explorer skipped: template not found at {template}")
        return

    with open(template, encoding="utf-8") as f:
        html = f.read()

    bootstrap = 'load(demoSnapshot(),"DEMO TOPOLOGY",false);'
    if bootstrap not in html:
        logger.warning("  HTML Explorer skipped: demo bootstrap line not found in template "
                       "(template may have changed).")
        return

    slim = _slim_for_embed(snap_dict)                  # NEW-V3.23.90: shrink the in-page payload only
    # BOTH values go through the same hardening. The label used to get a bare json.dumps() while the
    # payload beside it got the '</' treatment, and that asymmetry WAS the bug: json.dumps produces a
    # correct JS string literal but says nothing about the HTML <script> DATA context, so a label of
    # `pwn</script><script>alert(document.domain)</script>` closed the block early and the injected
    # script ran under the template's own `script-src 'unsafe-inline'` CSP. The label is
    # attacker-reachable -- AssessHub takes it as an unsanitized form field that falls back to the
    # UPLOADED FILENAME, stores it, and serves it back from the explorer route -- so this was stored
    # XSS with same-origin access to every stored client snapshot.
    embedded = _script_safe_json(slim)
    replacement = (f"const EMBEDDED_SNAPSHOT={embedded};\n"
                   f"load(EMBEDDED_SNAPSHOT,{_script_safe_json(label)},true);")

    # Replace ONLY the last occurrence (the bootstrap), not the button's onclick.
    head, _sep, tail = html.rpartition(bootstrap)
    patched = head + replacement + tail

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(patched)
    logger.info(f"[Phase 22] HTML Explorer embedded payload: {len(embedded) / 1e6:.1f} MB")
    logger.info(f"[Phase 22] HTML Explorer written: {output_path}")


# -----------------------------------------------------------------------------
# Snapshot redaction (opt-in --redact): pseudonymize IPs / MACs / serial numbers
# so a single-file HTML/JSON deliverable can be shared without leaking the real
# addressing. Mappings are CONSISTENT (same input -> same output) and IPs keep
# their /24 grouping, so ARP (MAC->IP), dual-homing, and subnet/flow-trace
# relationships the explorer relies on survive. Hostnames are intentionally kept.
# -----------------------------------------------------------------------------
_REDACT_IP_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_REDACT_MAC_RE = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b|\b(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4}\b")
# IPv6 (HTML_-01): the IPv4 remap above is dotted-quad ONLY, so IPv6 addresses (global 2001:db8::,
# link-local fe80::, embedded in descriptions) passed through --redact untouched -- the share-safe contract
# was broken for any dual-stack / IPv6 fleet. This matches the full 8-group and ::-compressed textual forms
# but NOT a colon-MAC (which has neither 7 colons nor a '::'), so the MAC remap stays correct regardless of
# order. Every alternative requires either 7 colons or a '::', and all quantifiers are bounded ({1,7}), so a
# long hex/colon run cannot induce catastrophic backtracking (ReDoS). An optional %zone-id is consumed.
_REDACT_IP6_RE = re.compile(
    r"(?<![:.\w])(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"                 # x:x:x:x:x:x:x:x  (7 colons; a MAC has 5)
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"                             # x::  …  x:x:x:x:x:x:x::
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"             # x::x … x:x:x:x:x:x::x
    r"|(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}"
    r"|[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}"
    r"|:(?::[0-9A-Fa-f]{1,4}){1,7}"                             # ::x  ::x:x  (loopback/unspecified-with-suffix)
    r")(?:%[0-9A-Za-z]+)?(?![:.\w])")
_REDACT_SERIAL_KEYS = {"serial_number", "chassis_serial",
                       "current_switch_serial", "neighbor_switch_serial",
                       # controller + inventory serials reach the snapshot under other key names: ACI
                       # fabric-node 'serial' (parse_aci_fabric_nodes -> snap['aci'].nodes) and the
                       # power-supply 'ps_serials' list (parse_show_inventory). Without these they leaked
                       # verbatim under --redact (a bare serial matches no inline secret form). 'ps_serials'
                       # is a LIST -- _walk recurses each string item with the same key, so each is redacted.
                       "serial", "ps_serials", "sn"}

# Credential deny-list: conservatively match KNOWN secret-bearing config/output forms
# (IOS / IOS-XE / NX-OS, case-insensitive) and replace ONLY the secret token with a
# placeholder, keeping the surrounding keywords as context. Each pattern captures the
# prefix in group 1 and the secret in group 2; the secret is swapped for "<redacted>".
# Idempotent: re-running over an already-scrubbed string re-captures "<redacted>" and
# substitutes it for itself. We are deliberately narrow (no blanket token redaction) so
# non-secret structured fields are never corrupted.
_REDACT_PLACEHOLDER = "<redacted>"
# A secret value may be a bare token or a quoted, space-bearing value.  Matching only ``\S+``
# changed ``set passphrase "correct horse battery staple"`` into
# ``set passphrase <redacted> horse battery staple"`` and the verifier then blessed the residue
# because the first token was the placeholder.  Consume one complete shell/config value instead.
_REDACT_SECRET_VALUE = r"""(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|\S+)"""
_REDACT_SECRET_RES = [re.compile(prefix + "(" + _REDACT_SECRET_VALUE + ")", re.I) for prefix in (
    # SNMP community strings: 'snmp-server community <VALUE>' and the bare
    # 'community <VALUE>' form (host/group/trap lines).
    r"(snmp-server\s+community\s+)",
    r"(\bcommunity\s+)",
    # 'snmp-server host <ip> [vrf X] [traps|informs] version {1|2c} <COMMUNITY>' -- the trap-host community is a
    # bare positional token with NO 'community' keyword to anchor on, so the two patterns above missed it and it
    # shipped verbatim under --redact (leak-corpus K4). v3 uses a username (not a secret), so only 1|2c match.
    r"(snmp-server\s+host\s+\S+\s+(?:vrf\s+\S+\s+)?(?:(?:traps?|informs?)\s+)?version\s+(?:1|2c)\s+)",
    # Cisco password/secret forms: type-7/type-5 and cleartext, 'enable secret',
    # and 'username <u> password|secret <VALUE>'. The username token is preserved.
    r"(\bpassword\s+(?:(?:ENC|\d+)\s+)?)",
    r"(\bsecret\s+(?:\d+\s+)?)",
    r"((?:username|user)\s+\S+\s+(?:password|secret)\s+(?:\d+\s+)?)",
    # Shared keys. Specific forms FIRST so the generic bare 'key' below cannot consume
    # their qualifier (e.g. 'pre-shared-key local <V>' must not let 'key local' match).
    # TACACS+/RADIUS server keys, 'key-string <VALUE>' (SNMPv3 / EIGRP / OSPF keychains),
    # IKE pre-shared keys, and 'crypto isakmp key <VALUE> address ...'.
    r"((?:tacacs-server|radius-server)\s+(?:host\s+\S+\s+)?key\s+(?:\d+\s+)?)",
    r"(key-string\s+(?:\d+\s+)?)",
    r"(pre-shared-key\s+(?:(?:local|remote|ascii-text|hexadecimal)\s+)?(?:\d+\s+)?)",
    r"(crypto\s+isakmp\s+key\s+(?:\d+\s+)?)",
    # Generic 'key 7 <hex>' / 'key <cleartext>' (keychain key, OSPF/EIGRP authentication). The optional
    # inner group absorbs a hash-algorithm label so 'authentication-key|message-digest-key N md5|sha|
    # hmac-sha <DIGEST>' (NTP/OSPF/EIGRP) redacts the DIGEST after it, not the 'md5'/'sha' token -- the
    # latter left the real, offline-crackable digest exposed. Anchored on 'key', so a bare IKE 'hash md5'
    # algorithm choice (no key-id + secret) is never corrupted. The negative lookahead keeps STRUCTURAL
    # follow-words intact: 'key chain <NAME>' declares a keychain (name is not a secret), and the bare rule
    # runs AFTER the pre-shared-key rule over the accumulating string, so without the guard it re-fired on
    # 'pre-shared-key local <redacted>' and mangled the 'local'/'remote' direction qualifier.
    r"((?<!private-)(?<!shared-)\bkey\s+(?:\d+\s+)?(?:(?:md5|sha\S*|hmac-\S+|cmac-\S+)\s+(?:\d+\s+)?)?)(?!chain\b|local\b|remote\b)",
    # Non-Cisco vendor config forms: FortiGate 'set passwd|psksecret|password [ENC] <VALUE>' and Junos
    # 'authentication-key|secret "<VALUE>"' -- 'passwd'/'psksecret' are not the whole words 'password'/'secret',
    # so the Cisco patterns above miss them.
    r"(set\s+(?:passwd|psksecret|password|private-key|passphrase)\s+(?:ENC\s+)?)",
)]
# JSON-VALUE secrets: the controller-REST channels (ACI / ISE / FMC / vManage) and IaC exports store a secret as
# a VALUE under a key, with no inline keyword for the deny-list regexes above to anchor on. So redact the WHOLE
# value when its key is a known secret-bearing name. Keys are normalized (lowercased, '_'/'-' stripped) before
# the lookup. 'key' is deliberately EXCLUDED -- it is a generic structural field name across the snapshot (causal
# flows, design decisions) and the inline 'key <val>' CLI form is already covered above.
_REDACT_SECRET_KEYS = {
    "password", "passwd", "pwd", "passphrase", "secret", "psksecret", "presharedkey", "psk",
    "token", "authtoken", "accesstoken", "apikey", "apisecret", "community", "snmpcommunity",
    "credential", "credentials", "privatekey", "sharedsecret", "clientsecret",
}   # 'pass' deliberately omitted -- it is a pass/fail COUNT key in security summaries, not a secret

# SUBSTRING tokens for a credential-named key -- the real controller/config field names are COMPOUND
# (tacacsSharedSecret, roCommunity, authPassword, wpaPassphrase, enableSecret), which an EXACT-match against the
# set above silently missed (multi-domain audit #6). A normalized key CONTAINING any token is a secret bearer.
# Bare 'key' and 'pass' are NOT tokens (generic structural field / pass-fail count) -- see _is_secret_key.
_REDACT_SECRET_TOKENS = (
    "password", "passwd", "passphrase", "secret", "community", "psk", "presharedkey", "sharedsecret",
    "token", "apikey", "apisecret", "privatekey", "privkey", "credential",
)

# CDP/LLDP 'Device ID: <host>(<SERIAL>)' embeds the neighbor's chassis serial in a free-text field that is NOT a
# serial-named key, so the key-based serial pass missed it (audit-5 sec HIGH: 55 real serials survived --redact).
# Match a parenthesized Cisco serial (3 letters + 4 digits + 2-6 alnum, e.g. FOC1830R1QS) so it routes through the
# SAME serial pseudonymizer for a consistent SNxxxx; the SNxxxx pseudonym (2 leading letters) never re-matches.
_REDACT_CDP_SERIAL_RE = re.compile(r"\(([A-Z]{3}[0-9]{4}[A-Z0-9]{2,6})\)")
# Cisco serials also occur in arbitrary prose and generated validation expectations, where no
# serial-shaped schema key or CDP parentheses exist.  Match the same deliberately narrow token
# shape independently of context; SN#### pseudonyms cannot re-match it, so the pass is idempotent.
_REDACT_INLINE_SERIAL_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{3}[0-9]{4}[A-Z0-9]{2,6})(?![A-Z0-9])",
    re.IGNORECASE,
)
_REDACT_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Z0-9-]+\.)+[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)

_SYNTH_DOMAIN = "assesshub-redacted.invalid"
_SYNTH_MARKER_RE = re.compile(
    r"(?:v4-n\d{5}-h\d{3}|v6-\d{8}|mac-\d{12}|serial-\d{6})\."
    + re.escape(_SYNTH_DOMAIN),
    re.IGNORECASE,
)
_SYNTH_SERIAL_RE = re.compile(
    r"serial-\d{6}\." + re.escape(_SYNTH_DOMAIN) + r"\Z",
    re.IGNORECASE,
)
_SYNTH_EMAIL_RE = re.compile(
    r"contact-\d{6}@" + re.escape(_SYNTH_DOMAIN) + r"\Z",
    re.IGNORECASE,
)
_MAX_V4_SYNTH_NETWORKS = 65_536
_MAX_SYNTH_IDENTITIES = 999_999


class RedactionPseudonymExhausted(RuntimeError):
    """The bounded synthetic namespace cannot issue another collision-free marker."""


class _SyntheticAllocator:
    """Issue unmistakably synthetic, bounded, collision-checked ``.invalid`` markers."""

    def __init__(self, reserved=None, limit: int = _MAX_SYNTH_IDENTITIES):
        self.reserved = set(reserved or ())
        self.issued = set()
        self.next_value = 1
        self.limit = int(limit)

    def issue(self, render) -> str:
        while self.next_value <= self.limit:
            value = render(self.next_value)
            self.next_value += 1
            if value in self.reserved or value in self.issued:
                continue
            self.issued.add(value)
            return value
        raise RedactionPseudonymExhausted(
            "bounded redaction pseudonym namespace exhausted; refusing partial redaction"
        )


def _existing_synthetic_markers(root) -> set:
    """Reserve producer-origin markers already present so a new identity cannot collide with one."""
    found = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            stack.extend(value)
        elif isinstance(value, str):
            found.update(match.group(0).casefold() for match in _SYNTH_MARKER_RE.finditer(value))
            found.update(match.group(0).casefold() for match in _REDACT_EMAIL_RE.finditer(value)
                         if _SYNTH_EMAIL_RE.fullmatch(match.group(0)))
    return found


def _norm_key(k) -> str:
    return re.sub(r"[_-]", "", str(k or "").lower())


def _scrub_secrets(s: str) -> str:
    """Replace known credential / community / key material in a config-or-output string
    with a placeholder, preserving surrounding context. Conservative (deny-list of
    compiled regexes, secret-token capture only) and idempotent."""
    for rx in _REDACT_SECRET_RES:
        s = rx.sub(r"\g<1>" + _REDACT_PLACEHOLDER, s)
    return s


def redact_snapshot(snap: dict) -> dict:
    """Return a copy of the snapshot with IPs, MACs, serial numbers, and emails consistently
    pseudonymized for sharing the single-file deliverable. Same input maps to the same
    output and IPs keep their /24 grouping, so topology / ARP / subnet relationships
    survive; hostnames are kept. Pure (stdlib only); the input is not mutated.
    COLLISION-PROOF IPv4 (same cure as _make_redactor's): pseudonym /24s are drawn from
    240.0.0.0/4 — the IANA-reserved Class E block no deployed device can carry — so a
    redacted deliverable can NEVER reproduce a real address. The old in-band
    10.{i//256}.{i%256} scheme could (net 10.0.20 drew '10.0.10', re-emitting the real
    gateway 10.0.10.1). A net ALREADY in 240.x maps to ITSELF: every IPv4 in a scrubbed
    output is 240.x, so that identity rule is exactly what keeps redact_snapshot
    idempotent (a second pass is a no-op)."""
    reserved = _existing_synthetic_markers(snap)
    ip_map: Dict[str, int] = {}
    ip6_map: Dict[str, str] = {}
    mac_map: Dict[str, str] = {}
    serial_map: Dict[str, str] = {}
    email_map: Dict[str, str] = {}
    ip6_allocator = _SyntheticAllocator(reserved)
    mac_allocator = _SyntheticAllocator(reserved)
    serial_allocator = _SyntheticAllocator(reserved)
    email_allocator = _SyntheticAllocator(reserved)
    _next_net = [1]

    def _ip(m):
        net = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        if net not in ip_map:
            while _next_net[0] <= _MAX_V4_SYNTH_NETWORKS:
                candidate = _next_net[0]
                _next_net[0] += 1
                if not any(
                    f"v4-n{candidate:05d}-h{host:03d}.{_SYNTH_DOMAIN}".casefold() in reserved
                    for host in range(256)
                ):
                    ip_map[net] = candidate
                    break
            if net not in ip_map:
                raise RedactionPseudonymExhausted(
                    "bounded IPv4 redaction namespace exhausted; refusing partial redaction"
                )
        return f"v4-n{ip_map[net]:05d}-h{int(m.group(4)):03d}.{_SYNTH_DOMAIN}"

    def _ip6(m):
        s = m.group(0)
        if s not in ip6_map:
            ip6_map[s] = ip6_allocator.issue(
                lambda i: f"v6-{i:08d}.{_SYNTH_DOMAIN}"
            )
        return ip6_map[s]

    def _mac(m):
        key = re.sub(r"[^0-9a-f]", "", m.group(0).lower())
        if key not in mac_map:
            mac_map[key] = mac_allocator.issue(
                lambda i: f"mac-{i:012d}.{_SYNTH_DOMAIN}"
            )
        return mac_map[key]

    def _serial(v):
        if not v:
            return v
        if _SYNTH_SERIAL_RE.fullmatch(str(v)):
            return v
        key = str(v).upper()
        if key not in serial_map:
            serial_map[key] = serial_allocator.issue(
                lambda i: f"serial-{i:06d}.{_SYNTH_DOMAIN}"
            )
        return serial_map[key]

    def _email(value):
        address = str(value)
        if _SYNTH_EMAIL_RE.fullmatch(address):
            return address
        key = address.casefold()
        if key not in email_map:
            email_map[key] = email_allocator.issue(
                lambda i: f"contact-{i:06d}@{_SYNTH_DOMAIN}"
            )
        return email_map[key]

    def _scrub_identity_tokens(s):
        """Pseudonymize serials outside email tokens, then pseudonymize real email addresses.

        Shielding each complete address from the serial matcher preserves approved example-domain
        placeholders even if their local part happens to look like a Cisco serial.
        """
        out = []
        cursor = 0

        def serials(chunk):
            chunk = _REDACT_CDP_SERIAL_RE.sub(
                lambda m: "(" + _serial(m.group(1)) + ")", chunk
            )
            return _REDACT_INLINE_SERIAL_RE.sub(lambda m: _serial(m.group(1)), chunk)

        for match in _REDACT_EMAIL_RE.finditer(s):
            out.append(serials(s[cursor:match.start()]))
            out.append(_email(match.group(0)))
            cursor = match.end()
        out.append(serials(s[cursor:]))
        return "".join(out)

    def _scrub(s):
        # Strip credentials / community / key material first so a secret token is replaced wholesale, THEN
        # pseudonymize any remaining IPv4 / IPv6 / MACs in context. IPv6 is remapped before MAC; the two
        # patterns are mutually exclusive (a MAC has neither 7 colons nor a '::'), so neither corrupts the other.
        s = _scrub_identity_tokens(_scrub_secrets(s))
        return _REDACT_MAC_RE.sub(_mac, _REDACT_IP6_RE.sub(_ip6, _REDACT_IP_RE.sub(_ip, s)))

    def _is_secret_key(key) -> bool:
        nk = _norm_key(key)
        if not nk or nk == "key":            # 'key' is a generic structural field name -- never a secret on its own
            return False
        return nk in _REDACT_SECRET_KEYS or any(tok in nk for tok in _REDACT_SECRET_TOKENS)

    def _redact_key(key):
        if not isinstance(key, str):
            return key
        return _scrub(key)

    def _store_preserving_key(out, safe_key, value):
        """Store a redacted key without silently overwriting a colliding original entry.

        Case variants of one serial intentionally share a stable ``SN####`` pseudonym, and a
        pre-existing pseudonym-shaped key may already occupy that spelling.  Preserve the first
        spelling and add a deterministic ordinal alias for every later collision.  The alias
        contains only the stable pseudonym, never the source serial.
        """
        candidate = safe_key
        if candidate in out:
            base = str(safe_key)
            ordinal = 2
            candidate = f"{base}~{ordinal}"
            while candidate in out:
                ordinal += 1
                candidate = f"{base}~{ordinal}"
        out[candidate] = value

    def _redact_all(o):
        # Every string leaf under a credential-named container is a secret bearer -- a secret nested one level
        # below the key ({'apikey':{'value':...}}) must not survive (multi-domain audit #7). Over-redacting
        # non-secret siblings (e.g. an 'enc: type6' tag) is the safe direction.
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                _store_preserving_key(out, _redact_key(k), _redact_all(v))
            return out
        if isinstance(o, list): return [_redact_all(v) for v in o]
        if isinstance(o, str): return _REDACT_PLACEHOLDER if o else o
        return o

    def _walk(o, key=None):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                safe_key = _redact_key(k)
                if isinstance(v, (dict, list)) and _is_secret_key(k):
                    # secret-named key over a CONTAINER -> scrub every leaf
                    safe_value = _redact_all(v)
                else:
                    safe_value = _walk(v, k)
                _store_preserving_key(out, safe_key, safe_value)
            return out
        if isinstance(o, list):
            return [_walk(v, key) for v in o]
        if isinstance(o, str):
            if key in _REDACT_SERIAL_KEYS: return _serial(o)
            if key == "wild": return o   # ACL wildcard mask is not an address; preserve so post-redact L4 eval stays correct
            if o and _is_secret_key(key):
                return _REDACT_PLACEHOLDER   # a secret stored as a JSON value under a credential-named key
            return _scrub(o)
        return o

    return _walk(snap)


def _make_redactor(reserved=None):
    """A fresh, self-consistent pseudonymizer (same scheme as redact_snapshot: IPv4 keeps its /24 grouping;
    IPv6 -> fd00::; MAC -> 02:..; serial -> SNxxxx). Returns (scrub_str, redact_serial) sharing per-call maps.
    Shared by redact_collected_inplace + redact_workbook_cells so the --redact workbook is scrubbed everywhere.
    COLLISION-PROOF IPv4 (same Class E scheme as redact_snapshot's map): pseudonym /24s are drawn from
    240.0.0.0/4 — the IANA-reserved Class E block that can never be assigned to real gear — so a pseudonym
    can NEVER reproduce a real deployed address. The old in-band 10.{i//256}.{i%256} scheme could: the
    NRFU sheet's second real SVI net drew the pseudonym '10.0.10', re-emitting the OTHER real gateway IP
    10.0.10.1 verbatim into a --redact workbook (and a net whose index matched its own name survived
    unredacted). Belt-and-braces guards keep a candidate from equalling the input net, an already-seen
    net, or an already-issued pseudonym even if a capture somehow contains 240.x addresses — unlike
    redact_snapshot, which must map an already-240.x net to ITSELF to stay idempotent, this per-call map
    is never re-fed its own output, so it refuses identity outright. Deterministic per call."""
    reserved = set(reserved or ())
    ip_map: Dict[str, int] = {}
    ip6_map: Dict[str, str] = {}
    mac_map: Dict[str, str] = {}
    serial_map: Dict[str, str] = {}
    email_map: Dict[str, str] = {}
    ip6_allocator = _SyntheticAllocator(reserved)
    mac_allocator = _SyntheticAllocator(reserved)
    serial_allocator = _SyntheticAllocator(reserved)
    email_allocator = _SyntheticAllocator(reserved)
    _next_ip = [1]

    def _ip(m):
        net = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        if net not in ip_map:
            while _next_ip[0] <= _MAX_V4_SYNTH_NETWORKS:
                candidate = _next_ip[0]
                _next_ip[0] += 1
                if not any(
                    f"v4-n{candidate:05d}-h{host:03d}.{_SYNTH_DOMAIN}".casefold() in reserved
                    for host in range(256)
                ):
                    ip_map[net] = candidate
                    break
            if net not in ip_map:
                raise RedactionPseudonymExhausted(
                    "bounded IPv4 redaction namespace exhausted; refusing partial redaction"
                )
        return f"v4-n{ip_map[net]:05d}-h{int(m.group(4)):03d}.{_SYNTH_DOMAIN}"

    def _ip6(m):
        s = m.group(0)
        if s not in ip6_map:
            ip6_map[s] = ip6_allocator.issue(
                lambda i: f"v6-{i:08d}.{_SYNTH_DOMAIN}"
            )
        return ip6_map[s]

    def _mac(m):
        key = re.sub(r"[^0-9a-f]", "", m.group(0).lower())
        if key not in mac_map:
            mac_map[key] = mac_allocator.issue(
                lambda i: f"mac-{i:012d}.{_SYNTH_DOMAIN}"
            )
        return mac_map[key]

    def serial(v):
        if not v:
            return v
        if _SYNTH_SERIAL_RE.fullmatch(str(v)):
            return v
        key = str(v).upper()
        if key not in serial_map:
            serial_map[key] = serial_allocator.issue(
                lambda i: f"serial-{i:06d}.{_SYNTH_DOMAIN}"
            )
        return serial_map[key]

    def email(v):
        address = str(v)
        if _SYNTH_EMAIL_RE.fullmatch(address):
            return address
        key = address.casefold()
        if key not in email_map:
            email_map[key] = email_allocator.issue(
                lambda i: f"contact-{i:06d}@{_SYNTH_DOMAIN}"
            )
        return email_map[key]

    def _identities(s):
        chunks = []
        cursor = 0

        def serials(chunk):
            chunk = _REDACT_CDP_SERIAL_RE.sub(
                lambda m: "(" + serial(m.group(1)) + ")", chunk
            )
            return _REDACT_INLINE_SERIAL_RE.sub(lambda m: serial(m.group(1)), chunk)

        for match in _REDACT_EMAIL_RE.finditer(s):
            chunks.append(serials(s[cursor:match.start()]))
            chunks.append(email(match.group(0)))
            cursor = match.end()
        chunks.append(serials(s[cursor:]))
        return "".join(chunks)

    def scrub(s):
        s = _identities(_scrub_secrets(s))
        return _REDACT_MAC_RE.sub(_mac, _REDACT_IP6_RE.sub(_ip6, _REDACT_IP_RE.sub(_ip, s)))

    return scrub, serial


#: Structured documents `redact_collection_dir` does NOT rewrite in place, and the scratch name it
#: writes while rewriting a capture. `_scrub_secrets` is a grammar over line-oriented device-config
#: text (``snmp-server community <V>``, ``username u password <V>``); it does not read structured
#: data, substituting inside a serialised document is how a capture stops parsing, and rewriting a
#: generated ``.html`` deliverable that happens to sit in the collection folder would break the run
#: manifest that already sealed it. These are the ONLY exclusions — see `_is_raw_capture` — they
#: are the same set the independent verifier applies
#: (`webapp.backend.redaction_verify._STRUCTURED_CAPTURE_SUFFIXES`), and that verifier reports them
#: under ``uncovered`` rather than letting the silence read as "clean".
#:
#: RULE OWNER: ``webapp.backend.redaction_verify.is_uncoverable_capture`` states this rule for the
#: independent verifier AND for the ingest census (``ingest._is_raw_capture`` delegates to it), so it
#: is the owner of record. The producer cannot import it — ``cisco_toolkit`` must not depend on
#: ``webapp``, and the verifier's independence forbids importing the producer — so the rule is
#: RESTATED here with the SAME suffix set and the SAME primitive: the owner's own expression,
#: ``PurePath(name).suffix.casefold()`` (see `_capture_suffix`).
#:
#: Two earlier restatements used a DIFFERENT primitive and each opened a hole. ``str.endswith``
#: disagreed on bare-name dotfiles (the producer skipped ``.json`` as structured while the verifier
#: scanned it as a capture). ``os.path.splitext(name)[1]`` replaced it under a comment claiming the
#: two were byte-for-byte identical — they are not, ``splitext`` skips ALL leading dots on the
#: basename and ``PurePath.suffix`` skips only the first — so they disagreed on every name with two
#: or more leading dots. Suffix-of-a-name is deceptively easy to restate and has now been restated
#: wrongly twice, which is why the rule has ONE owner and ``tests/test_redact_collection.py`` pins
#: the two against each other over a GENERATED corpus of that structural class rather than a
#: hand-list of examples.
_REDACT_SKIP_CAPTURE_SUFFIXES = frozenset({".json", ".xml", ".yml", ".yaml", ".html", ".htm"})
_REDACT_SCRUB_TEMP_SUFFIX = ".redacting"
#: Deliberate BOUND on the widened (default-INCLUDE) rule — see `redact_collection_dir`. Mirrors the
#: verifier's ``redaction_verify.MAX_ARTIFACT_BYTES``: a file larger than this is not a device
#: capture, and reading it whole into memory to rewrite the engineer's only copy is the wrong risk to
#: take on a field laptop. Skipped files are DISCLOSED (returned), never silently dropped.
_REDACT_MAX_CAPTURE_BYTES = 128 * 1024 * 1024


def _capture_suffix(filename: str) -> str:
    """The basename's final extension, casefolded — the ONE primitive both sides of the raw-capture
    rule use.

    This is the OWNER's own expression, not a paraphrase of it: the independent verifier computes
    ``Path(filename).suffix.casefold()``, and ``Path.suffix`` IS ``PurePath.suffix`` on every
    platform, so this cannot drift from it.

    It is deliberately NOT ``os.path.splitext(filename)[1]``, which stood here under a comment
    asserting the two were byte-for-byte identical. Measured over a generated corpus of 168 names
    they return different strings for 51, and for names with two or more leading dots the difference
    changes the CLASSIFICATION: ``splitext("..json")[1]`` is ``""`` (⇒ a capture) while
    ``PurePath("..json").suffix`` is ``".json"`` (⇒ a structured serialisation the scrub must not
    touch). Measured consequence with the old primitive: `redact_collection_dir` rewrote
    ``CORE-1/..json`` in place until it no longer parsed (``Expecting ',' delimiter``) while the
    verifier declared the same file uncoverable, and the count reconciliation at
    ``COLLECT_PARSE_V3_23_0.py:4267`` then failed the whole run with "producer/verifier raw-capture
    file counts disagree"."""
    return PurePath(filename or "").suffix.casefold()


def _is_raw_capture(filename: str) -> bool:
    """Is ``filename`` a raw device capture the in-place secret scrub owns? (name half.)

    The old test was ``fn.endswith(".txt")`` — a single extension standing in for the class
    "collected capture text". A device folder holding ``show_version.txt`` alongside
    ``backup-config.cfg`` or ``show_tech-support.log`` is accepted everywhere else in this
    codebase, and those two were never scrubbed: measured, they kept cleartext ``enable secret``,
    ``snmp-server community`` and ``username ... password`` values through a run that reported the
    captures SCRUBBED and exited 0.

    So the default is now INCLUDE, and only the two structural exclusions above opt out. An
    extension nobody anticipated (``.conf``, ``.cfg``, ``.log``, ``.out``, none at all) is a
    capture and gets scrubbed — the failure mode is inverted from "unknown ⇒ leaked" to
    "unknown ⇒ protected". The content half of the rule (binary bytes are not a capture) is
    applied at the read in `redact_collection_dir`, because only the bytes can decide it.

    Matched with `_capture_suffix`, which is the OWNER's primitive verbatim — not `str.endswith`
    (which disagreed on bare-name dotfiles: ``.json`` has no extension, so the verifier counted it a
    capture while the endswith form skipped it) and not `os.path.splitext` (which disagreed on names
    with two or more leading dots: ``..json``). Two matchers for one rule is two rules; see
    `_REDACT_SKIP_CAPTURE_SUFFIXES` for who owns it and what each divergence cost."""
    suffix = _capture_suffix(filename)
    return suffix != _REDACT_SCRUB_TEMP_SUFFIX and suffix not in _REDACT_SKIP_CAPTURE_SUFFIXES


class _ScrubResult(tuple):
    """``(scanned, changed)`` — plus ``.uncovered``, the files this pass declined to rewrite.

    A plain 2-tuple, so every existing ``scanned, changed = redact_collection_dir(...)`` caller and
    every ``== (1, 1)`` assertion keeps working unchanged; the coverage list rides alongside as an
    attribute instead of being visible only in a ``logger.debug`` line nobody reads at a client site.
    Each entry is ``(relative_path, reason)``."""

    def __new__(cls, scanned: int, changed: int, uncovered=()):
        self = super().__new__(cls, (scanned, changed))
        self.uncovered = tuple(uncovered)
        return self


def redact_collection_dir(collection_dir: str) -> tuple:
    """Plan A / Tier-1 #5: scrub SECRET VALUES (passwords / communities / keys — the same
    conservative _scrub_secrets deny-list --redact uses) IN PLACE across every collected
    text capture under collection_dir (see `_is_raw_capture`; NOT just ``*.txt``). Values
    only: IPs / hostnames / interfaces are KEPT
    so the dir stays analyzable with --no-collect and remains the --compare/--trend
    source; nothing is ever deleted. Idempotent (the placeholder never re-matches).
    Returns (txt_files_scanned, files_changed). Fail-soft per file — one unreadable
    capture never aborts the scrub of the rest. Note: rewritten captures will no longer
    match archive hashes recorded at collection time (deliberate, opt-in).

    BYTE FIDELITY (the promise above is "values only; nothing is ever deleted", and it was
    being broken twice on the engineer's ONLY copy of the raw captures):
    * ``errors="surrogateescape"`` on BOTH read and write round-trips bytes that are not valid
      UTF-8 exactly. ``errors="ignore"`` silently DELETED them — e.g. 0x96, the cp1252 en-dash
      that shows up in real banners and interface descriptions.
    * ``newline=""`` on both sides stops text mode rewriting every ``\\n`` to ``\\r\\n`` on
      Windows, which changed every line of every scrubbed capture.
    * temp file + ``os.replace`` makes the rewrite atomic: a yank or a full disk mid-write left
      a truncated capture that is indistinguishable from a legitimate scrub, because the run
      manifest was sealed a phase earlier.

    THE BOUND (because `_is_raw_capture` defaults to INCLUDE, this pass can otherwise reach any text
    file anywhere under the collection root, and it rewrites the engineer's only copy in place).
    Four deliberate limits, none of them a list of names, and every exclusion is DISCLOSED in the
    returned ``.uncovered`` rather than left in a debug log:

    1. the name rule (structured serialisations + the scrub's own scratch suffix) — `_is_raw_capture`;
    2. binary content — a NUL byte anywhere means this is a container, not line-oriented capture text;
    3. size — over `_REDACT_MAX_CAPTURE_BYTES` (the verifier's own artifact ceiling) nothing is even
       read: a 200 MB blob in a collection folder is a core dump or a pcap, not a ``show`` capture;
    4. the grammar itself — a file is only ever REWRITTEN when `_scrub_secrets` actually matched a
       secret line in it, so an unrelated ``.md`` or ``.csv`` that happens to sit under the root is
       read and left byte-identical.

    Returns ``(scanned, changed)`` (a `_ScrubResult`, so ``.uncovered`` carries limits 1-3)."""
    scanned = changed = 0
    uncovered: List[tuple] = []
    base = collection_dir or ""

    def _rel(path: str) -> str:
        try:
            return os.path.relpath(path, base).replace(os.sep, "/")
        except ValueError:                      # different drive on Windows -- name it absolutely
            return path

    for root, _dirs, files in os.walk(base):
        for fn in files:
            p = os.path.join(root, fn)
            if not _is_raw_capture(fn):
                uncovered.append((_rel(p), "not a raw capture by name (structured serialisation "
                                           "or the scrub's own scratch file)"))
                continue
            try:
                size = os.path.getsize(p)
            except OSError as e:
                logger.debug(f"redact_collection_dir: unsizeable {p}: {e}")
                uncovered.append((_rel(p), f"size could not be read ({e.__class__.__name__})"))
                continue
            if size > _REDACT_MAX_CAPTURE_BYTES:
                # Bound 3. Not read, not rewritten, not counted as scanned -- and said out loud,
                # because "we did not look at this one" must never arrive as part of a clean count.
                logger.warning(f"redact_collection_dir: {p} is {size} bytes (> "
                               f"{_REDACT_MAX_CAPTURE_BYTES}); NOT scrubbed and NOT scanned")
                uncovered.append((_rel(p), f"{size} bytes exceeds the {_REDACT_MAX_CAPTURE_BYTES}-byte "
                                           "capture ceiling; not read, so not scrubbed"))
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    text = f.read()
            except Exception as e:
                logger.debug(f"redact_collection_dir: unreadable {p}: {e}")
                uncovered.append((_rel(p), f"unreadable ({e.__class__.__name__})"))
                continue
            if "\x00" in text:
                # The content half of the capture rule. A NUL byte means binary; the deny-list
                # grammar would read noise out of it, and rewriting it is the one thing the
                # BYTE FIDELITY contract above must never risk. Not counted as scanned either --
                # a file this pass declines to protect must not inflate its own coverage number.
                logger.debug(f"redact_collection_dir: binary, not a capture: {p}")
                uncovered.append((_rel(p), "binary content (a NUL byte), not a text capture"))
                continue
            scanned += 1
            scrubbed = _scrub_secrets(text)
            if scrubbed != text:
                tmp = p + ".redacting"
                try:
                    with open(tmp, "w", encoding="utf-8", errors="surrogateescape",
                              newline="") as f:
                        f.write(scrubbed)
                    os.replace(tmp, p)      # atomic: the capture is either old or new, never half
                    changed += 1
                except Exception as e:
                    logger.warning(f"redact_collection_dir: could not rewrite {p}: {e}")
                    try:
                        os.unlink(tmp)      # never leave a partial beside the real capture
                    except OSError:
                        pass
                    uncovered.append((_rel(p), f"secrets were found but the rewrite FAILED "
                                               f"({e.__class__.__name__}); the original is unchanged "
                                               "and still holds them"))
    uncovered.sort()
    return _ScrubResult(scanned, changed, uncovered)


def redact_collected_inplace(all_interfaces: dict, all_device_physical: list) -> None:
    """Pseudonymize the COLLECTED dataclasses (InterfaceData + DevicePhysical) IN PLACE, so the always-produced
    .xlsx workbook -- which the sheet builders assemble from these dataclasses BEFORE redact_snapshot ever runs on
    the JSON -- cannot leak real serials / IPs / MACs under --redact. Serial-named fields -> SNxxxx; every other
    string -> IP/IPv6/MAC/secret scrub. For the --redact share-safe path only; mutates in place. Never raises.
    (Sheets built from COMPUTED structures / raw config text, not these dataclasses, are caught separately by
    redact_workbook_cells.)"""
    import dataclasses as _dc
    values = []
    for dp in (all_device_physical or []):
        try:
            values.extend(getattr(dp, f.name, "") for f in _dc.fields(dp))
        except TypeError:
            pass
    for ports in (all_interfaces or {}).values():
        for obj in (ports or {}).values():
            try:
                values.extend(getattr(obj, f.name, "") for f in _dc.fields(obj))
            except TypeError:
                pass
    scrub, serial = _make_redactor(_existing_synthetic_markers(values))

    def _red_obj(o):
        try:
            fields = _dc.fields(o)
        except TypeError:
            return                                    # not a dataclass instance -> nothing to redact
        for f in fields:
            v = getattr(o, f.name, "")
            if isinstance(v, str) and v:
                # serial-named field -> consistent SNxxxx; everything else -> pattern scrub (catches an IP/MAC in
                # ANY field, so a leak can't hide in a free-text column we forgot to enumerate).
                setattr(o, f.name,
                        serial(v) if (f.name in _REDACT_SERIAL_KEYS or f.name.endswith("_serial")) else scrub(v))

    for dp in (all_device_physical or []):
        _red_obj(dp)
    for ports in (all_interfaces or {}).values():
        for d in (ports or {}).values():
            _red_obj(d)


def redact_workbook_cells(wb) -> None:
    """Final-pass --redact safety net: scrub IPv4/IPv6/MACs/credentials from EVERY cell of an openpyxl workbook,
    so sheets built from COMPUTED structures (e.g. Subnet Reachability) or RAW config text (Golden-Config Drift)
    -- which redact_collected_inplace can't reach because they don't come from the collected dataclasses -- cannot
    leak real addresses/secrets. Serials carry no reliable text pattern, so they are pseudonymized upstream in the
    dataclasses; this pass covers everything pattern-matchable. Mutates in place; never raises."""
    try:
        sheets = list(wb.worksheets)
    except Exception as exc:
        raise RuntimeError("workbook cells could not be enumerated for redaction") from exc
    values = [
        cell.value
        for ws in sheets
        for row in ws.iter_rows()
        for cell in row
        if isinstance(cell.value, str)
    ]
    scrub, _ = _make_redactor(_existing_synthetic_markers(values))
    for ws in sheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v:
                    nv = scrub(v)
                    if nv != v:
                        cell.value = nv
