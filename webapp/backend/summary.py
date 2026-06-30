"""Derive a dashboard summary from a raw engine snapshot.

This is a *read-only projection* of the snapshot the engine already computed — it never re-runs
analysis. It rolls the headline numbers (re-using the engine's own `_trend_point`) plus the
breakdowns the cockpit needs: health bands, punch-list by severity/category, keystone devices by
blast radius, readiness, and which detail sections actually carry data (so the UI hides empty tabs).
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import engine

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"]
_SEV_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}
BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"]


def _as_list(v: Any) -> List[Any]:
    """Coerce a snapshot section to a list. `(snap.get(k) or [])` only guards falsy values; a truthy
    NON-list (an int/str/dict in a malformed or hostile upload) would flow into a list-comprehension and
    raise TypeError -- summarize() runs on every upload, so that escapes as an HTTP 500. Returning [] for a
    non-list degrades gracefully, honouring this function's `Every field degrades gracefully` contract."""
    return v if isinstance(v, list) else []

# Detail sections the web UI can render as tabs, in display order. (key, human label)
SECTION_LABELS: List[tuple] = [
    ("punchlist", "Punch-list"),
    ("device_dossiers", "Risk register"),     # NEW-V3.23.174 (per-asset compound-risk register)
    ("health_scores", "Health scores"),
    ("failure_impact", "Failure impact"),
    ("link_centrality", "Chokepoints"),
    ("causality", "Causality"),
    ("cross_layer", "Cross-layer"),
    ("migration_readiness", "Readiness"),
    ("wave_sequencing", "Wave sequencing"),
    ("application_intelligence", "Application domains"),
    ("segmentation", "Segmentation"),
    ("protocol_health", "Protocols"),
    ("multicast_intelligence", "Multicast / timing"),
    ("remediation_plan", "Remediation"),
    ("validation_plan", "Validation plan"),
    ("golden_drift", "Config drift"),
    # NEW-V3.23.176: the V3.23.164-.167 NOS analytic quartet landed after this list was
    # authored and was unreachable from the web platform (neither tab nor whitelist) --
    # the one-source-of-truth audit's only real gap.
    ("syslog_intelligence", "Syslog"),
    ("qos_audit", "QoS posture"),
    ("software_risk", "Software risk"),
    ("platform_health", "Platform health"),
    ("capacity", "Capacity"),
    ("endpoint_identity", "Endpoints"),
    ("lifecycle_risk", "Lifecycle / EoL"),
    ("collection_completeness", "Collection completeness"),
]


def _count_by(items: List[dict], key: str, order: List[str] | None = None) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        v = str(it.get(key, "") or "—")
        out[v] = out.get(v, 0) + 1
    if order:
        ordered = {k: out.get(k, 0) for k in order if k in out}
        for k, v in out.items():  # any value not in the canonical order, appended
            ordered.setdefault(k, v)
        return ordered
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _keystones(snap: Dict[str, Any], top: int = 8) -> List[Dict[str, Any]]:
    """The few devices the fleet most depends on, by migration blast radius.

    Prefer the engine's own executive-brief keystones; else derive from failure_impact
    (stranded endpoints, severity), which is always present."""
    eb = snap.get("executive_brief")
    eb = eb if isinstance(eb, dict) else {}      # a truthy non-dict section must not raise (malformed upload)
    if isinstance(eb.get("keystones"), list) and eb["keystones"]:
        return eb["keystones"][:top]
    fi = [r for r in _as_list(snap.get("failure_impact")) if isinstance(r, dict)]
    fi.sort(key=lambda r: (_SEV_RANK.get(r.get("severity", ""), 99),
                           -int(r.get("stranded", 0) or 0)))
    return [{
        "host": r.get("host", ""),
        "severity": r.get("severity", ""),
        "stranded": r.get("stranded", 0),
        "vlans_impacted": r.get("vlans_impacted", 0),
        "detail": r.get("detail", ""),
    } for r in fi[:top]]


def _section_index(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Which detail sections carry data + a count, for tab visibility."""
    out = []
    for key, label in SECTION_LABELS:
        v = snap.get(key)
        if isinstance(v, list):
            count = len(v)
        elif isinstance(v, dict):
            # dict sections: count the most meaningful list inside, else number of keys
            inner = next((x for x in v.values() if isinstance(x, list)), None)
            count = len(inner) if inner is not None else len(v)
        else:
            count = 0
        if count:
            out.append({"key": key, "label": label, "count": count})
    return out


def summarize(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Headline + breakdowns used by the dashboard cards. Every field degrades gracefully."""
    hs = [r for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)]
    pl = [r for r in _as_list(snap.get("punchlist")) if isinstance(r, dict)]
    mr = [r for r in _as_list(snap.get("migration_readiness")) if isinstance(r, dict)]

    try:
        head = engine.trend_point(snap)  # re-use the engine's headline extractor
    except Exception:
        head = {}                        # a malformed upload must degrade, not 500 the dashboard summary

    readiness = {"READY": 0, "CAUTION": 0, "NOT READY": 0}
    for r in mr:
        if r.get("readiness") in readiness:
            readiness[r["readiness"]] += 1

    _lr = snap.get("lifecycle_risk")
    _lrs = (_lr if isinstance(_lr, dict) else {}).get("summary")    # a truthy NON-dict summary (e.g. an older
    lr = _lrs if isinstance(_lrs, dict) else {}                     # engine's "not computed" string) must not 500

    return {
        "version": snap.get("script_version", ""),
        "n_switches": head.get("n_switches", len(snap.get("devices") or {})),
        "avg_health": head.get("avg_health", ""),
        "bands": _count_by(hs, "band", BANDS),
        "n_critical": head.get("n_critical", 0),
        "punchlist": {
            "total": len(pl),
            "by_severity": _count_by(pl, "severity", SEVERITY_ORDER),
            "by_category": _count_by(pl, "category"),
            "crit_high": head.get("n_crit_high", 0),
        },
        "readiness": readiness,
        "keystones": _keystones(snap),
        "lifecycle": {
            "past_eos": lr.get("n_past_eos", ""),
            "near_eos": lr.get("n_near", ""),          # canonical Near-LDoS count (was a non-existent n_near_eos -> always blank)
            "past_ldos": lr.get("n_past_ldos", ""),
        } if lr else {},
        "sections": _section_index(snap),
    }
