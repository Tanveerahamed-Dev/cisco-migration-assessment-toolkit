"""Unified CAUSAL FLOW model — every finding family as one trigger -> mechanism -> impact -> mitigation story.

Python-canonical mirror of the ``causalFlows()`` JS in ``blast_radius_explorer.html``. The AssessHub webapp
reads THIS via ``GET /api/snapshots/{id}/causal_flows`` so the dashboard never re-derives causal intent (one
source of truth) — exactly as it does for the design blueprint. The explorer keeps its own verified JS port
(it is standalone HTML); both read the SAME engine-emitted snapshot fields and produce the same shape, so the
two surfaces cannot disagree.

Sources, de-duplicated:
  * Structural SPOF   <- snap["causality"]                 (rich trigger/mechanism/impact/mitigation)
  * Cross-layer       <- snap["cross_layer"]               (multi-cause compounds -> bowtie)
  * Design decision   <- snap["design_blueprint"]["decisions"]  (status == "recommended" only)
  * all other families<- snap["punchlist"]                 (every category EXCEPT "Cross-layer", already covered)

Nothing here re-computes a finding: each row renders the engine's own output. Pure function of ``snap``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# 4-level semantic severity ramp: (CSS colour token, rank). Low/Info map to a real token (no "--neutral").
_SEV: Dict[str, Tuple[str, int]] = {
    "Critical": ("crit", 5), "High": ("risk", 4), "Medium": ("watch", 3),
    "Low": ("accent", 2), "Info": ("accent", 1),
}
# per-family glyph for the filter chips (geometric — renders consistently across fonts)
_FAMILY_ICON: Dict[str, str] = {
    "struct": "⤳", "xlayer": "⧉", "design": "✎", "Compound risk": "❖",
    "Addressing": "⌖", "FHRP": "⮂", "False-health": "❢",
    "Health": "✚", "L1": "━", "L3": "⇄", "Operational logs": "☰",
    "Protocol": "⇆", "Security": "⛨", "Software exposure": "⌗", "Inventory": "▤",
    "Multicast/Media": "⋔", "QoS": "⊜", "STP": "⎇", "Timing/PTP": "◷",
}


def _sev(s: Any) -> str:
    t = str(s or "").lower()
    if "crit" in t:
        return "Critical"
    if t == "high" or "warn" in t or "error" in t:
        return "High"
    if "med" in t:
        return "Medium"
    if "low" in t:
        return "Low"
    # hashable-safe: only return the raw value when it is a string that is a valid _SEV key, else Info.
    # (guards `s in _SEV` against unhashable severities like a dict, and guarantees _SEV[_sev(s)] is total.)
    return s if (isinstance(s, str) and s in _SEV) else "Info"


def _sev_rank(s: Any) -> int:
    return _SEV[_sev(s)][1]


# Type guards mirroring the explorer JS Array.isArray gates: a truthy non-list/non-dict (e.g. the string
# "notalist") must NOT slip through an `x or []` idiom and get iterated character-by-character. These keep
# compute_causal_flows total over ANY dict so the webapp endpoint can never 500 on a malformed snapshot.
def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


# singular form per unit so a count of 1 reads "1 device", not "1 devices" (applied only when n == 1)
_SINGULAR = {"endpoints": "endpoint", "devices": "device", "hosts": "host", "switches": "switch", "VLANs": "VLAN"}
# base magnitude keywords scanned in priority order; a family may pass extra (lower-priority) units.
_BLAST_UNITS = (("endpoint", "endpoints"), ("device", "devices"), ("host", "hosts"), ("switch", "switches"))


def _blast(text: Any, hosts: Any, extra_units: Tuple[Tuple[str, str], ...] = ()) -> Tuple[int, str]:
    """Best-available blast magnitude as ``(n, unit)`` — coverage-honest: the unit is the one actually
    matched in the prose (endpoints preferred, then devices/hosts/switches, then any ``extra_units`` the
    caller supplies), so a count is never mislabeled. Falls back to the host/device count. The cross-layer
    family passes ``("VLAN","VLANs")`` so a transit-partition finding surfaces "51 VLANs" (its own headline)
    instead of the lone host removed."""
    s = str(text or "")

    def pick(kw: str) -> Optional[int]:
        m = re.search(r"(\d[\d,]*)\s*" + kw, s, re.I)
        return int(m.group(1).replace(",", "")) if m else None

    for kw, unit in _BLAST_UNITS + tuple(extra_units):
        n = pick(kw)
        if n is not None:
            return n, (_SINGULAR.get(unit, unit) if n == 1 else unit)
    if isinstance(hosts, list):
        n = len(hosts)
        return n, ("device" if n == 1 else "devices")
    return 0, "devices"


def _flow(key: str, family: str, family_label: str, title: str, severity: Any, hosts: List[str],
          trigger: str, mechanism: str, impact: str, mitigation: str, blast: int, blast_unit: str,
          shape: str, evidence: Optional[dict] = None, icon: Optional[str] = None) -> Dict[str, Any]:
    sv = _sev(severity)
    return {
        "key": key, "family": family, "family_label": family_label,
        "icon": icon if icon is not None else _FAMILY_ICON.get(family, "•"),
        "title": title or "", "severity": sv, "sev_tok": _SEV[sv][0],
        "trigger": trigger or "", "mechanism": mechanism or "", "impact": impact or "",
        "mitigation": mitigation or "", "hosts": hosts, "blast": blast, "blast_unit": blast_unit,
        "shape": shape, "evidence": evidence or {},
    }


def compute_causal_flows(snap: Optional[dict]) -> Dict[str, Any]:
    """Return ``{flows, families, summary}`` — the unified, severity-ranked causal-flow list for a snapshot."""
    snap = _as_dict(snap)
    devices = set(_as_dict(snap.get("devices")).keys())

    def in_model(h: Any) -> bool:
        if not isinstance(h, str):     # device keys are strings; an unhashable host can't match the set anyway
            return False
        return (not devices) or (h in devices)

    flows: List[Dict[str, Any]] = []

    # 1) Structural SPOF
    for i, c in enumerate(_as_list(snap.get("causality"))):
        if not isinstance(c, dict):
            continue
        hosts = [h for h in _as_list(c.get("hosts")) if in_model(h)][:8]
        n, unit = _blast(c.get("impact"), hosts)
        flows.append(_flow(
            f"struct-{i}", "struct", "Structural SPOF",
            c.get("trigger") or f"Structural SPOF {i + 1}", c.get("severity"), hosts,
            c.get("trigger", ""), c.get("mechanism", ""), c.get("impact", ""), c.get("mitigation", ""),
            n, unit, "linear", evidence={"fields": ["causality"]}))

    # 2) Cross-layer -> bowtie when >= 2 contributing causes can be read faithfully
    for i, x in enumerate(_as_list(snap.get("cross_layer"))):
        if not isinstance(x, dict):
            continue
        hosts = [h for h in _as_list(x.get("hosts")) if in_model(h)][:8]
        layers = [s.strip() for s in re.split(r"[+,/&]", str(x.get("layers") or "")) if s.strip()]
        clauses = [s.strip() for s in re.split(r";|\s+\band\b\s+", str(x.get("detail") or ""), flags=re.I)
                   if len(s.strip()) > 6]
        threats = (clauses if len(clauses) >= 2 else layers)[:3]
        # cross-layer findings headline a VLAN count ("…partitions endpoints in 51 VLAN(s)") — surface it as
        # the magnitude (after any endpoint/device count) so the badge matches the finding's own title.
        n, unit = _blast(x.get("detail"), hosts, (("VLAN", "VLANs"),))
        mech = ("Two layers compound: " + " + ".join(layers)) if layers else "Independent weaknesses align"
        f = _flow(
            f"cl-{i}", "xlayer", "Cross-layer",   # index, not x['id'] — CL-xx ids repeat (303 share "CL-02")
            x.get("title") or f"Cross-layer {x.get('id') or i + 1}", x.get("severity"), hosts,
            x.get("detail", ""), mech, x.get("detail", ""), x.get("recommendation", ""),
            n, unit, "bowtie" if len(threats) >= 2 else "linear",
            evidence={"layers": x.get("layers"), "fields": ["cross_layer"]})
        f["threats"] = threats
        f["top_event"] = x.get("title") or ""
        f["consequence"] = x.get("detail") or ""
        flows.append(f)

    # 3) Design decisions (recommended only) — driver -> principle -> evidence -> recommended action
    bp = _as_dict(snap.get("design_blueprint"))
    for i, d in enumerate(_as_list(bp.get("decisions"))):
        if not isinstance(d, dict) or d.get("status") != "recommended":
            continue
        ev = _as_dict(d.get("evidence"))
        devs = _as_list(ev.get("devices"))
        hosts = [h for h in devs if in_model(h)][:8]
        cnt = int(ev.get("count")) if isinstance(ev.get("count"), (int, float)) and not isinstance(ev.get("count"), bool) else None
        # BLAST = the affected-DEVICE count (what a blast-radius badge means). The metric `cnt` counts whatever
        # the decision is about -- ports / VLANs / member-legs / trunks / root-elections / move-groups -- and
        # stays in the TITLE with its own unit; labelling `cnt` as 'device(s)' was a LIVE mislabel (e.g. a chip
        # reading '1339 device(s)' for 1339 ports). When a fleet-level decision carries no device list, fall back
        # to the metric under the unit-neutral 'affected' rather than asserting a unit we cannot name.
        n_dev = len(devs)
        if n_dev:
            blast, blast_unit, impact = n_dev, ("device" if n_dev == 1 else "devices"), f"{n_dev} device(s) carry this gap"
        elif cnt:
            blast, blast_unit, impact = cnt, "affected", f"{cnt} affected by this gap"
        else:
            blast, blast_unit, impact = 0, "devices", "Target-state design risk"
        f = _flow(
            f"design-{d.get('id') or i}", "design", "Design decision",
            d.get("title", ""), d.get("priority"), hosts,
            ev.get("summary") or d.get("driver", ""),
            d.get("driver") or _as_dict(d.get("principle")).get("title", ""),
            impact,
            d.get("recommended_action", ""), blast, blast_unit, "linear",
            evidence={"count": cnt, "devices": devs, "fields": ev.get("fields"),
                      "citation": _as_dict(d.get("principle")).get("citation")})
        f["confidence"] = d.get("confidence") or ""
        f["alternatives"] = d.get("alternatives") or ""
        f["tradeoffs"] = d.get("tradeoffs") or ""
        f["axes"] = _as_list(d.get("axes"))
        flows.append(f)

    # 4) Punch-list — every remaining family (Cross-layer already covered by its rich array above)
    for i, p in enumerate(_as_list(snap.get("punchlist"))):
        if not isinstance(p, dict):
            continue
        cat = str(p.get("category") or "Finding")
        if cat == "Cross-layer":
            continue
        devs = _as_list(p.get("devices"))
        hosts = [h for h in devs if in_model(h)][:8]
        n, unit = _blast(p.get("detail"), devs)
        if n > 0:
            impact = f"{n} {unit} affected" + (f" · {p.get('wave')}" if p.get("wave") else "")
        else:
            impact = p.get("detail") or f"{len(devs)} device(s) affected"
        flows.append(_flow(
            f"pl-{i}", cat, cat, p.get("title") or cat, p.get("severity"), hosts,
            p.get("title", ""), p.get("detail", ""), impact, p.get("remediation", ""),
            n, unit, "linear",
            evidence={"devices": devs, "rank": p.get("rank"), "wave": p.get("wave"), "fields": ["punchlist"]},
            icon=_FAMILY_ICON.get(cat, "•")))

    # severity-rank, then blast magnitude
    flows.sort(key=lambda f: (-_sev_rank(f["severity"]), -(f["blast"] or 0)))

    # family roster (ordered by criticals then volume)
    fam: Dict[str, Dict[str, Any]] = {}
    for f in flows:
        e = fam.setdefault(f["family"], {"key": f["family"], "label": f["family_label"],
                                         "icon": f["icon"], "n": 0, "crit": 0})
        e["n"] += 1
        if _sev_rank(f["severity"]) >= 4:
            e["crit"] += 1
    families = sorted(fam.values(), key=lambda e: (-e["crit"], -e["n"]))

    by_sev: Dict[str, int] = {}
    for f in flows:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    return {
        "flows": flows,
        "families": families,
        "summary": {
            "n_flows": len(flows),
            "n_families": len(families),
            "n_critical": sum(1 for f in flows if _sev_rank(f["severity"]) >= 5),
            "by_severity": by_sev,
        },
    }
