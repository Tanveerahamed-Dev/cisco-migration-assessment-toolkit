"""Named, persisted segmentation / path assertions (roadmap G3) — offline, read-only, coverage-honest.

Forward Networks and IP Fabric let you SAVE a path search as a named intent check with an expected outcome
(status:delivered) AND first-class isolation intents ("there must be NO path from A to B"). Recast offline:
a committed JSON catalog of {id, src, dst, expect} evaluated over the EXISTING `fib.trace_fib_path`, and
re-validated across the `--compare` pair so a cutover that breaks a required path (or opens an isolation) is
caught before the window. We already own the forwarding engine; this is the assertion + regression layer.

COVERAGE-HONEST (the critic's binding guard): `ISOLATED` is an EXISTENTIAL NEGATIVE — a single
`computed:unreachable` proves it, a reach refutes it, but a LOWER-BOUND trace (incomplete collection) can
NEVER prove isolation -> `not_observed`. Same for `REACHES` on a lower bound. We never fabricate a verdict.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import fib


def _classify(trace: Dict[str, Any], expect: str) -> str:
    """A single trace + an expectation -> 'pass' | 'fail' | 'not_observed'."""
    status = str(trace.get("status", "") or "")
    computed = bool(trace.get("computed"))
    reached = bool(trace.get("reached"))
    e = (expect if isinstance(expect, str) else "").strip()
    if not e:
        return "not_observed"                   # blank / non-string expect -> nothing to certify
    eu = e.upper()
    if eu == "REACHES":
        if not computed:
            return "not_observed"               # a lower bound -> we cannot confirm the required reachability
        return "pass" if reached else "fail"
    if eu == "ISOLATED":
        if not computed:
            return "not_observed"               # cannot PROVE no-path from an incomplete trace
        return "fail" if reached else "pass"     # reached => isolation violated; computed:unreachable => isolated holds
    low = e.lower().replace(" ", "")             # normalize 'status == x' spacing
    if low.startswith("status=="):
        want = low.split("==", 1)[1]
        if not want or not computed:             # blank target, or a lower-bound trace -> cannot certify a hard verdict
            return "not_observed"
        return "pass" if status.lower() == want else "fail"
    return "not_observed"                        # unknown verb -> abstain, never a fabricated verdict


def evaluate_path_assertions(snap: Dict[str, Any], assertions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate a catalog of path/segmentation assertions over one snapshot -> {results, summary}.

    Each assertion is {id, title?, src, dst, expect: REACHES|ISOLATED|status==<x>}. Each result carries the
    verdict, the computed `fib` status, and a citation to the computed path. Pure; offline."""
    results: List[dict] = []
    for a in assertions or []:
        src, dst = a.get("src"), a.get("dst")
        expect = a.get("expect", "REACHES")
        tr = fib.trace_fib_path(snap, src, dst) if (src and dst) else {"status": "lower_bound:bad_address", "computed": False, "reached": False}
        verdict = _classify(tr, expect)
        results.append({
            "id": a.get("id"), "title": a.get("title", ""), "src": src, "dst": dst, "expect": expect,
            "verdict": verdict, "status": tr.get("status"), "reached": bool(tr.get("reached")),
            "citation": "computed path %s -> %s (%s)" % (src, dst, tr.get("status")),
        })
    summary = {"pass": 0, "fail": 0, "not_observed": 0}
    for r in results:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    summary["n"] = len(results)
    return {"results": results, "summary": summary}


def revalidate(old_snap: Dict[str, Any], new_snap: Dict[str, Any], assertions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Re-evaluate the catalog across the --compare pair -> per-assertion {old_verdict, new_verdict, regressed}.

    `regressed` is True when an assertion that PASSED on the baseline no longer passes after the change (a
    broken required path, or an isolation that can no longer be proven) — the pre-cutover regression signal."""
    o = {r["id"]: r for r in evaluate_path_assertions(old_snap, assertions)["results"]}
    n = {r["id"]: r for r in evaluate_path_assertions(new_snap, assertions)["results"]}
    rows: List[dict] = []
    for a in assertions or []:
        aid = a.get("id")
        ov = o.get(aid, {}).get("verdict", "not_observed")
        nv = n.get(aid, {}).get("verdict", "not_observed")
        rows.append({
            "id": aid, "expect": a.get("expect", "REACHES"),
            "old_verdict": ov, "new_verdict": nv,
            # a regression is a NEW definite failure (pass->fail OR not_observed->fail = a newly-proven breach);
            # losing the proof (pass->not_observed) is a coverage gap, NOT a regression (never overclaim 'not observed').
            "regressed": (nv == "fail" and ov != "fail"),
            "coverage_lost": (ov == "pass" and nv == "not_observed"),
            "old_status": o.get(aid, {}).get("status"), "new_status": n.get(aid, {}).get("status"),
        })
    summary = {"n": len(rows),
               "regressed": sum(1 for r in rows if r["regressed"]),
               "coverage_lost": sum(1 for r in rows if r["coverage_lost"])}
    return {"results": rows, "summary": summary}
