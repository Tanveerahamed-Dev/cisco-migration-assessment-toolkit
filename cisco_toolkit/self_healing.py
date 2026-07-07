"""Remediation nerve (Phase 4) — PROPOSE-ONLY self-healing triage over the ``--compare`` drift.

Phase 4 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``. The self-healing loop is:
**detect** (a regression between a baseline and the current snapshot — or, in Phase 5, an intel-feed PSIRT
hit) → **root-cause** (a read-only analyst) → **author a remediation MOP with rollback** (mop-change-author)
→ **twin-verify** (Batfish, Phase 6, CLI-half only) → **propose as a PR + CAB** → **human approves** →
**NRFU confirms recovery** (nrfu-validator). **Never a device write** — the change is always a reviewable
artifact, and the author never certifies its own fix (proposer ≠ verifier).

This module is the **triage core**: it reads two snapshots, extracts the drift from grounded fields
(``health_scores[*].score/band`` and ``architecture_coverage[*].status``), assigns a severity, **routes each
item to the right specialist**, and emits a **propose-only remediation plan** — a root-cause owner, a MOP
author, an independent verifier, a natural-language remediation *intent* (never a device command), a rollback
(restore the baseline), and an NRFU acceptance. It proposes; it applies nothing.

**Distinct from** :func:`cisco_toolkit.analyze.compute_remediation_plan`, which generates per-device,
platform-tagged config *snippets* FOR REVIEW from the current findings. This module is the *loop above* it:
detect the drift between two snapshots, route it, and orchestrate the propose-only MOP → NRFU cycle — the MOP
author can draw on that generator's review snippets, but nothing here emits or applies config.

Coverage-honest: a health drop where either side is 'Insufficient Data' is a *data-quality* signal, not a
regression; a class going ``not-observed → finding`` is flagged but noted as possibly *new visibility*, not a
new fault; and no drift yields "nothing to remediate" said plainly (it compares two snapshots — it is **not**
an assertion the network is healthy). Pure — reads only the two dicts; the coverage recompute is a lazy
import. The actual spawning of analysts/authors is the ``/remediate`` command's job.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SEV_ORDER = ["Critical", "High", "Medium", "Low"]

# Which read-only analyst root-causes a finding in each domain pack (reuses the D6 pack→domain map).
_PACK_ROOT_CAUSE = {
    "sec": "config-security-auditor",
    "dc": "topology-reachability-analyst",
    "ent": "topology-reachability-analyst",
    "sp": "topology-reachability-analyst",
}
_DEFAULT_ROOT_CAUSE = "topology-reachability-analyst"


def _coverage(snap: Any) -> Dict[str, Any]:
    cov = snap.get("architecture_coverage") if isinstance(snap, dict) else None
    if isinstance(cov, dict) and cov.get("classes"):
        return cov
    try:
        from cisco_toolkit.design_advisor import compute_architecture_coverage
        return compute_architecture_coverage(snap)
    except Exception:
        return {"classes": []}


def _health_index(snap: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in (snap.get("health_scores") if isinstance(snap, dict) else None) or []:
        if isinstance(r, dict) and r.get("switch"):
            out[r["switch"]] = r
    return out


def _health_severity(delta: float, new_band: Any) -> str:
    if str(new_band) == "Critical":
        return "Critical"
    if delta >= 30:
        return "High"
    if delta >= 15:
        return "Medium"
    return "Low"


def extract_drift(old_snap: Any, new_snap: Any, *, score_drop: int = 10) -> List[Dict[str, Any]]:
    """The regressions between baseline (``old``) and current (``new``). Pure; reads only the two dicts."""
    drift: List[Dict[str, Any]] = []
    old_h, new_h = _health_index(old_snap), _health_index(new_snap)
    for sw, nr in new_h.items():
        orr = old_h.get(sw)
        if not orr:
            continue
        if "Insufficient Data" in (str(orr.get("band")), str(nr.get("band"))):
            continue                                  # data-quality, not a real regression (coverage-honest)
        os_, ns = orr.get("score"), nr.get("score")
        if isinstance(os_, (int, float)) and isinstance(ns, (int, float)) and ns <= os_ - score_drop:
            drift.append({"kind": "health", "subject": sw, "old": os_, "new": ns, "delta": os_ - ns,
                          "severity": _health_severity(os_ - ns, nr.get("band")),
                          "detail": f"health {os_}->{ns} ({orr.get('band')}->{nr.get('band')})"})
    oc = {c["key"]: c for c in _coverage(old_snap).get("classes", []) if isinstance(c, dict) and c.get("key")}
    for c in _coverage(new_snap).get("classes", []):
        if not isinstance(c, dict) or c.get("status") != "finding":
            continue
        k, prev = c.get("key"), oc.get(c.get("key"), {})
        fired = ", ".join(c.get("findings") or [])
        if prev.get("status") == "clean":
            drift.append({"kind": "coverage", "subject": k, "label": c.get("label"), "old": "clean",
                          "new": "finding", "severity": "High",
                          "detail": f"{c.get('label')} regressed clean->finding: {fired}"})
        elif prev.get("status") == "not-observed":
            drift.append({"kind": "coverage", "subject": k, "label": c.get("label"), "old": "not-observed",
                          "new": "finding", "severity": "Medium",
                          "detail": f"{c.get('label')} newly-observed finding: {fired} "
                                    f"(may be new visibility, not a new fault)"})
    drift.sort(key=lambda d: SEV_ORDER.index(d["severity"]))
    return drift


def _route(item: Dict[str, Any]) -> str:
    if item["kind"] == "coverage":
        from cisco_toolkit.domain_packs import PACKS
        for pid, spec in PACKS.items():
            if item.get("subject") in spec["classes"]:
                return _PACK_ROOT_CAUSE.get(pid, _DEFAULT_ROOT_CAUSE)
    return _DEFAULT_ROOT_CAUSE


def _intent(item: Dict[str, Any]) -> str:
    if item["kind"] == "health":
        return (f"Root-cause the health regression on {item['subject']} ({item['detail']}) and propose the "
                f"minimal restore — author it as a reviewable MOP; do NOT emit a device command.")
    return (f"Investigate and clear the '{item.get('label') or item['subject']}' finding ({item['detail']}); "
            f"propose the remediation as a reviewable MOP with rollback, never a device write.")


def propose_remediation(old_snap: Any, new_snap: Any, *, baseline_id: str = "baseline",
                        score_drop: int = 10) -> Dict[str, Any]:
    """The propose-only remediation plan. Each item names a root-cause owner, a MOP author, an independent
    verifier, the remediation *intent* (never a command), the rollback, and the NRFU acceptance. Applies
    nothing; the whole thing is a reviewable proposal (PR + CAB)."""
    drift = extract_drift(old_snap, new_snap, score_drop=score_drop)
    plan: List[Dict[str, Any]] = []
    for d in drift:
        plan.append({
            "subject": d.get("label") or d["subject"], "kind": d["kind"], "severity": d["severity"],
            "detail": d["detail"], "root_cause_owner": _route(d), "mop_author": "mop-change-author",
            "verifier": "nrfu-validator", "proposed_intent": _intent(d),
            "rollback": (f"revert to baseline snapshot '{baseline_id}'; the change is a reviewable PR, "
                         f"applied only inside a CAB maintenance window"),
            "verify": ("NRFU re-check + --compare(current -> remediated) shows the regression cleared and "
                       "introduces no new regression (proposer != verifier)"),
        })
    worst = plan[0]["severity"] if plan else None
    note = ((f"{len(plan)} propose-only remediation item(s); worst severity {worst}. "
             f"PROPOSE-ONLY — never a device write.") if plan else
            ("no regressions between baseline and current — nothing to remediate (coverage-honest: this "
             "compares the two snapshots; it is not an assertion that the network is healthy)."))
    return {"drift": drift, "plan": plan, "worst_severity": worst, "note": note,
            "doctrine": ("detect -> root-cause -> remediation MOP+rollback -> twin-verify -> PR+CAB -> human "
                         "-> NRFU-confirm; proposer != verifier; never a device write (D5)")}


def render(res: Dict[str, Any]) -> str:
    L = [f"Remediation triage — {res['note']}", f"  doctrine: {res['doctrine']}"]
    for i, p in enumerate(res["plan"], 1):
        L.append(f"  {i}. [{p['severity']}] {p['subject']} ({p['kind']}) — {p['detail']}")
        L.append(f"       root-cause: {p['root_cause_owner']} -> MOP: {p['mop_author']} -> verify: {p['verifier']}")
        L.append(f"       intent: {p['proposed_intent']}")
        L.append(f"       rollback: {p['rollback']}")
    return "\n".join(L)


def main(argv: List[str] = None) -> int:
    """CLI: ``python -m cisco_toolkit.self_healing <baseline.snapshot.json> <current.snapshot.json>`` ->
    print the propose-only remediation plan. Read-only; proposes nothing to any device."""
    import json
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    paths = [a for a in argv if not a.startswith("-")]
    if len(paths) < 2:
        print("usage: python -m cisco_toolkit.self_healing <baseline.snapshot.json> <current.snapshot.json>")
        return 2
    try:
        old = json.load(open(paths[0], encoding="utf-8"))
        new = json.load(open(paths[1], encoding="utf-8"))
    except Exception as e:
        print(f"could not read snapshots: {e!r}")
        return 2
    res = propose_remediation(old, new, baseline_id=paths[0])
    print(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
