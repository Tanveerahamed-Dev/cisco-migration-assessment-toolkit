"""Per-feature ConfigCompliance decomposition (roadmap I2) — offline, read-only.

Nautobot Golden Config's `ComplianceRule` owns config compliance per FEATURE (a feature -> match_config
ownership map), reporting per-feature `{compliant, missing[]}` and a device = AND-over-features rollup.
Our `compute_golden_drift` (analyze.py:4228) already computes the per-device delta against a supplied or
fleet-consensus baseline; this is a pure PROJECTION of that delta into per-(device x feature) rows, so a
reviewer sees *which* policy area drifted (aaa / ntp / snmp / logging / …) instead of one flat number.

No new collection, no change to compute_golden_drift; it consumes that function's output verbatim.
"""
from __future__ import annotations

from typing import Any, Dict, List

# feature -> ordered config-line prefixes it owns (normalized, lower-cased — matching golden-drift's lines).
# First feature whose prefix matches wins; an unmatched line falls into 'other' (coverage-honest: never dropped).
_FEATURE_MAP = [
    ("aaa", ("aaa ",)),
    ("ntp", ("ntp ",)),
    ("snmp", ("snmp-server ", "snmp ")),
    ("logging", ("logging ",)),
    ("vty/mgmt", ("line vty", "line con", "line aux", "transport input", "ip ssh", "ssh ")),
    ("dhcp-snooping", ("ip dhcp snooping",)),
    ("spanning-tree", ("spanning-tree ",)),
    ("qos", ("mls qos", "qos ", "policy-map", "class-map", "service-policy")),
    ("routing", ("router ", "ip route ", "ipv6 route ", "ip routing")),
    ("acl", ("ip access-list", "ipv6 access-list", "access-list ")),
    ("vlan", ("vlan ",)),
    ("services", ("service ", "no service ", "ip http", "no ip http")),
    ("banner", ("banner ",)),
]


def _feature_of(line: str) -> str:
    s = (line or "").lower().strip()
    if s[:3] == "re:":                      # golden-file 're:<pattern>' requirement -> classify by the pattern body
        s = s[3:].lstrip()
    for feat, prefixes in _FEATURE_MAP:
        if any(s.startswith(p) for p in prefixes):
            return feat
    return "other"


def compute_feature_compliance(golden_drift: Dict[str, Any]) -> Dict[str, Any]:
    """compute_golden_drift() output -> per-(device x feature) compliance rows + a per-feature rollup.

    Returns {features:[{feature,n_baseline,n_drifting}], per_device_feature:[{host,feature,n_baseline,
    n_missing,missing[],status}], summary:{…}}. A feature is emitted per device only when the baseline
    actually owns >= 1 line for it (so 'na' areas never read as a confident 'compliant')."""
    gd = golden_drift or {}
    baseline = gd.get("baseline") or []
    per_device = gd.get("per_device") or []

    feat_baseline: Dict[str, set] = {}
    for b in baseline:
        feat_baseline.setdefault(_feature_of(b), set()).add(b)

    rows: List[dict] = []
    feat_drift: Dict[str, int] = {f: 0 for f in feat_baseline}
    for d in per_device:
        host = d.get("host")
        missing = set(d.get("missing") or [])
        miss_by_feat: Dict[str, set] = {}
        for m in missing:
            miss_by_feat.setdefault(_feature_of(m), set()).add(m)
        for feat in sorted(feat_baseline):
            base = feat_baseline[feat]
            mm = sorted(m for m in miss_by_feat.get(feat, set()) if m in base)
            status = "compliant" if not mm else "drift"
            if status == "drift":
                feat_drift[feat] += 1
            rows.append({"host": host, "feature": feat, "n_baseline": len(base),
                         "n_missing": len(mm), "missing": mm[:20], "status": status})

    features = [{"feature": f, "n_baseline": len(feat_baseline[f]), "n_drifting": feat_drift[f]}
                for f in sorted(feat_baseline)]
    features.sort(key=lambda x: (-x["n_drifting"], x["feature"]))
    summary = {"n_features": len(features), "n_rows": len(rows),
               "n_drift_rows": sum(1 for r in rows if r["status"] == "drift")}
    return {"features": features, "per_device_feature": rows, "summary": summary}
