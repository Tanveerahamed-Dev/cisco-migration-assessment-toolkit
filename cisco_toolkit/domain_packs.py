"""Domain skill-pack selection (Phase 3, D6) — "the team that shows up is the one the network needs."

Phase 3 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``. The domain expertise (DC/ACI ·
Enterprise/SD-Access · SP/MPLS-SR · Security/ISE-TrustSec-firewalls) is a **retrieval/skill layer**, NOT a
parallel headcount of standing agents — decision **D6** (MAS-PromptBench: coordination goes *negative* at
8–10 agents; the roster is already at 8). A pack is a knowledge doc + a domain review checklist; it is
**selected by evidence**, keyed to the snapshot's ``architecture_coverage``, and surfaced on demand (a
``/council`` lens). The standing roster stays at 8.

**Selection is coverage-honest.** A pack loads **iff at least one of its architecture CLASSES was
OBSERVED** in the evidence — the DC pack loads iff ACI / VXLAN-overlay / Arista is actually present, not by
default. A *not-observed* class never loads a pack (absence is absence, never "no domain concerns"). The
pack→class map is pinned to the authoritative :data:`cisco_toolkit.design_advisor._ARCH_COVERAGE_REGISTRY`
by ``tests/test_domain_packs.py`` (every mapped class must exist in the registry, and every registry class
must have a pack — so a new detector can't create an architecture with no domain lens).

Pure-stdlib; :func:`select_packs` reads only the coverage dict passed in (no engine import), so it is
unit-testable without a snapshot. The registry cross-check imports the registry lazily.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

# pack id -> (title, knowledge/checklist doc, the architecture-coverage CLASS KEYS this domain reviews).
# The keys are _ARCH_COVERAGE_REGISTRY axes. A class may appear in >1 pack when it genuinely needs two
# lenses (access-edge port-security is campus AND security). The signature fabrics are unambiguous —
# aci -> DC only, ise -> Security only — so an ACI+ISE snapshot loads exactly {dc, sec}.
PACKS: Dict[str, Dict[str, Any]] = {
    "dc": {
        "title": "DC / ACI",
        "doc": "docs/packs/dc.md",
        "classes": {"aci", "overlay", "arista"},
    },
    "ent": {
        "title": "Enterprise / SD-Access",
        "doc": "docs/packs/enterprise.md",
        "classes": {"lisp", "fhrp_detail", "port_security", "storm_control", "pim", "ipv6_fhs",
                    "ipv6_nd", "ipv6_routing", "qos_runtime", "shadow_infra", "sdwan", "dmvpn", "crypto"},
    },
    "sp": {
        "title": "SP / MPLS-SR",
        "doc": "docs/packs/sp.md",
        "classes": {"mpls", "bfd"},
    },
    "sec": {
        "title": "Security / ISE-TrustSec-firewalls",
        "doc": "docs/packs/security.md",
        "classes": {"cts", "ise", "firewall", "fmc", "fortigate", "juniper", "cloud", "copp",
                    "ntp", "port_security"},
    },
}


def _observed_and_findings(coverage: Any) -> Tuple[Set[str], Set[str]]:
    """(observed class keys, class keys whose status is 'finding') from an architecture_coverage dict.
    Defensive: a non-dict / missing coverage yields empty sets (absence is absence)."""
    observed: Set[str] = set()
    findings: Set[str] = set()
    classes = coverage.get("classes", []) if isinstance(coverage, dict) else []
    for c in classes if isinstance(classes, list) else []:
        if isinstance(c, dict) and c.get("observed") and c.get("key"):
            observed.add(c["key"])
            if c.get("status") == "finding":
                findings.add(c["key"])
    return observed, findings


def select_packs(coverage: Any) -> Dict[str, Any]:
    """Which domain packs to load for a snapshot's ``architecture_coverage``.

    A pack loads iff one of its architecture classes was OBSERVED. Each selected pack reports the observed
    classes that triggered it and which of those carry findings (so the review is prioritized). Empty /
    absent coverage -> no packs, said plainly (never "no domain concerns"). Pure — no engine import."""
    observed, findings = _observed_and_findings(coverage)
    order = {pid: i for i, pid in enumerate(PACKS)}
    selected: List[Dict[str, Any]] = []
    for pid, spec in PACKS.items():
        hit = sorted(observed & spec["classes"])
        if hit:
            selected.append({"pack": pid, "title": spec["title"], "doc": spec["doc"],
                             "triggered_by": hit, "with_findings": sorted(findings & spec["classes"])})
    selected.sort(key=lambda s: order[s["pack"]])
    note = (f"{len(selected)} pack(s) loaded: {', '.join(s['pack'] for s in selected)}" if selected else
            "no domain packs loaded — no assessed architecture class was OBSERVED in this snapshot "
            "(coverage-honest: absence is absence, not 'no domain concerns')")
    return {"selected": selected, "loaded": [s["pack"] for s in selected], "note": note}


def registry_class_keys() -> Set[str]:
    """The authoritative architecture-coverage class keys, from _ARCH_COVERAGE_REGISTRY (lazy import)."""
    from cisco_toolkit.design_advisor import _ARCH_COVERAGE_REGISTRY
    return {axis for axis, *_rest in _ARCH_COVERAGE_REGISTRY}


def mapped_class_keys() -> Set[str]:
    """Every class key referenced by any pack."""
    keys: Set[str] = set()
    for spec in PACKS.values():
        keys |= spec["classes"]
    return keys


def render_selection(coverage: Any) -> str:
    """Human-readable pack selection."""
    sel = select_packs(coverage)
    L = [f"Domain packs — {sel['note']}"]
    for s in sel["selected"]:
        fnd = f"   [findings: {', '.join(s['with_findings'])}]" if s["with_findings"] else ""
        L.append(f"  {s['pack']:<4} {s['title']:<34} <- {', '.join(s['triggered_by'])}{fnd}")
    return "\n".join(L)


def main(argv: List[str] = None) -> int:
    """CLI: given a snapshot JSON, print which domain packs it loads. Uses the published
    ``architecture_coverage`` if present, else computes it. Read-only."""
    import json
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    path = next((a for a in argv if not a.startswith("-")), None)
    if not path:
        print("usage: python -m cisco_toolkit.domain_packs <snapshot.json>")
        return 2
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        print(f"could not read snapshot: {e!r}")
        return 2
    coverage = snap.get("architecture_coverage")
    if not isinstance(coverage, dict):
        try:
            from cisco_toolkit.design_advisor import compute_architecture_coverage
            coverage = compute_architecture_coverage(snap)
        except Exception as e:
            print(f"could not compute architecture_coverage: {e!r}")
            return 2
    print(render_selection(coverage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
