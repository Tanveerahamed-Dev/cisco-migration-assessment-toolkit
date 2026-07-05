"""Pre-Change Validation Certificate (orchestration roadmap C1) — offline, read-only, coverage-honest.

Forward Networks' "Predict" / Cisco NDI pre-change analysis / NetBrain's "Triple Defense" all certify a
candidate change before the maintenance window. The engine already ships the differential core
(`fib.reachability_delta`, live in `--compare`); this module packages it — plus the segmentation posture and
any `--path-intents` catalog re-validated across the pair — as the named PPDIOO gate ARTIFACT: a
decision-grade certificate JSON (`<output>.precert.json`) and a 'Pre-Change Certificate' diff-workbook sheet.

Verdict doctrine (encoded EXACTLY; coverage-honest):
  * any regression (newly-blocked flow / broken path intent / violated segmentation invariant) -> FAIL;
  * no regressions but >0 inconclusive flows or not_evaluable invariants -> CONDITIONAL — a certificate is
    never PASS with an open blind spot;
  * everything checkable checked and clean -> PASS;
  * nothing definitively checkable at all -> INDETERMINATE — we certify nothing we did not compute.
Every changed flow is cited `before -> after`; every blind spot is NAMED in `blind_spots`. Pure stdlib over
two already-collected snapshots; no egress, no device contact; total on malformed input.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import fib
from .path_assertions import revalidate

SCHEMA = "precert/1"

# The diff-workbook sheet contract (write_diff_workbook renders the certificate from these).
CERT_SHEET_NAME = "Pre-Change Certificate"
CERT_SHEET_HEADERS = ("Section", "Item", "Before", "After", "Disposition", "Evidence / Detail")

_VERDICTS = ("PASS", "CONDITIONAL", "FAIL", "INDETERMINATE")


def _stamp(snap: Dict[str, Any]) -> dict:
    """Provenance reference for one side of the pair: when it was generated, by which engine, over how many
    devices — the certificate is only as good as the snapshots it binds."""
    s = snap if isinstance(snap, dict) else {}
    devs = s.get("devices")
    return {"generated_at": str(s.get("generated_at", "") or ""),
            "script_version": str(s.get("script_version", "") or ""),
            "n_devices": len(devs) if isinstance(devs, dict) else 0}


def _inconclusive_reason(pair: dict) -> str:
    """NAME the blind spot: which side(s) of the trace were lost to incomplete collection, and how."""
    bits = []
    for label, key in (("before", "old_status"), ("after", "new_status")):
        status = str(pair.get(key, "") or "")
        if not status.startswith("computed"):
            bits.append(f"{label}: {status or 'not traced'}")
    return "; ".join(bits) or "trace not computed end-to-end"


def _flows(delta: dict) -> dict:
    """The reachability_delta reshaped for the certificate: preserved/both-unreachable counts, every changed
    flow cited old->new (regression = newly blocked), every inconclusive flow with its named reason, and the
    bounded-sample disclosure (no silent caps)."""
    changed: List[dict] = []
    for p in (delta.get("newly_blocked") or []):
        changed.append({"src": p.get("src"), "dst": p.get("dst"),
                        "before": p.get("old_status"), "after": p.get("new_status"), "regression": True})
    for p in (delta.get("newly_reachable") or []):
        changed.append({"src": p.get("src"), "dst": p.get("dst"),
                        "before": p.get("old_status"), "after": p.get("new_status"), "regression": False})
    inconclusive = [{"src": p.get("src"), "dst": p.get("dst"), "reason": _inconclusive_reason(p)}
                    for p in (delta.get("inconclusive_pairs") or [])]
    return {"preserved": int(delta.get("preserved") or 0),
            "both_unreachable": int(delta.get("both_unreachable") or 0),
            "changed": changed, "inconclusive": inconclusive,
            "assessed": bool(delta.get("assessed")),
            "pairs_tested": int(delta.get("pairs_tested") or 0),
            "subnets_tested": int(delta.get("subnets_tested") or 0),
            "subnets_total": int(delta.get("subnets_total") or 0),
            "capped": bool(delta.get("capped"))}


def _seg_of(snap: Dict[str, Any]) -> dict:
    v = snap.get("segmentation") if isinstance(snap, dict) else None
    return v if isinstance(v, dict) else {}


def _segmentation_invariants(snap_before: Dict[str, Any], snap_after: Dict[str, Any]) -> List[dict]:
    """Segmentation invariants derived from the BEFORE snapshot's posture (isolated app domains + dedicated
    VRFs) and re-checked on the AFTER side. `held` is a first-class tri-state: True / False (a violated
    invariant = a regression) / 'not_evaluable' (the data to re-verify it is absent — an abstention, never
    silently 'held'). A before snapshot with segmentation data but NO claim (flat network) yields no rows:
    nothing was claimed, so nothing can be violated or blind."""
    b, a = _seg_of(snap_before), _seg_of(snap_after)
    b_domains = [d for d in (b.get("domains") or []) if isinstance(d, dict)]
    b_vrfs = [v for v in (b.get("vrfs") or []) if isinstance(v, dict)]
    if not (b_domains or b_vrfs):
        return [{"invariant": "segmentation posture preserved", "held": "not_evaluable",
                 "evidence": "no segmentation data in the before snapshot — invariants cannot be derived "
                             "(NOT a statement that segmentation is unchanged)"}]
    a_domains = {str(d.get("domain")): d for d in (a.get("domains") or []) if isinstance(d, dict)}
    a_vrf_names = {str(v.get("vrf")) for v in (a.get("vrfs") or []) if isinstance(v, dict)}
    a_has = bool(a_domains) or bool(a_vrf_names)
    rows: List[dict] = []
    for d in b_domains:
        if not d.get("isolated"):
            continue                       # not isolated before -> no isolation invariant to preserve
        name = str(d.get("domain"))
        inv = f"application domain '{name}' remains isolated"
        ad = a_domains.get(name)
        if not a_has:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "no segmentation data in the after snapshot — isolation cannot be re-verified"})
        elif ad is None:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "domain absent from the after snapshot's segmentation data — "
                                     "isolation cannot be re-verified"})
        else:
            rows.append({"invariant": inv, "held": bool(ad.get("isolated")),
                         "evidence": str(ad.get("exposure", "") or
                                         ("still isolated after the change" if ad.get("isolated")
                                          else "no longer isolated after the change"))})
    for v in b_vrfs:
        name = str(v.get("vrf", "") or "")
        if not name or name == "(global)":
            continue                       # the global table is not a segmentation claim
        inv = f"VRF '{name}' still segments its gateways"
        n_gw = v.get("gateway_count", 0)
        if not a_has:
            rows.append({"invariant": inv, "held": "not_evaluable",
                         "evidence": "no segmentation data in the after snapshot — VRF presence cannot be re-verified"})
        elif name in a_vrf_names:
            rows.append({"invariant": inv, "held": True,
                         "evidence": f"{n_gw} gateway(s) before; VRF still present after the change"})
        else:
            rows.append({"invariant": inv, "held": False,
                         "evidence": f"VRF absent after the change — {n_gw} gateway(s) lost their VRF segmentation"})
    return rows


def compute_precert(snap_before: Dict[str, Any], snap_after: Dict[str, Any],
                    path_intents: Optional[List[dict]] = None,
                    limit: int = 24, max_pairs: int = 400) -> dict:
    """The Pre-Change Validation Certificate for a before/after snapshot pair (+ an optional path-intent
    catalog). Returns the certificate dict (schema 'precert/1'); pure JSON types; total on bad input."""
    before = snap_before if isinstance(snap_before, dict) else {}
    after = snap_after if isinstance(snap_after, dict) else {}

    try:                                   # fail-open: a reachability hiccup degrades to 'not assessed'
        delta = fib.reachability_delta(before, after, limit=limit, max_pairs=max_pairs)
    except Exception:
        delta = {}
    flows = _flows(delta)
    segmentation = _segmentation_invariants(before, after)

    intents: List[dict] = []
    intents_failed = False
    if path_intents:
        try:                               # fail-open, but NEVER silently drop a supplied catalog
            intents = revalidate(before, after, path_intents)["results"]
        except Exception:
            intents_failed = True

    # ---- regressions: every one cited (any regression => FAIL) ----
    regressions: List[str] = []
    for f in flows["changed"]:
        if f["regression"]:
            regressions.append(f"flow {f['src']} -> {f['dst']} newly blocked ({f['before']} -> {f['after']})")
    for s in segmentation:
        if s["held"] is False:
            regressions.append(f"segmentation invariant violated: {s['invariant']} — {s['evidence']}")
    for i in intents:
        if i.get("regressed"):
            regressions.append(f"path intent '{i.get('id')}' regressed "
                               f"({i.get('old_verdict')} -> {i.get('new_verdict')})")

    # ---- blind spots: every one NAMED (>0 open => never PASS) ----
    blind_spots: List[str] = []
    if not flows["assessed"]:
        blind_spots.append("computed reachability not assessed — "
                           + ("no routes collected" if flows["subnets_total"] == 0 else
                              f"only {flows['subnets_total']} subnet(s) collected, no inter-subnet flow to test"))
    elif flows["capped"]:
        blind_spots.append(f"reachability sample capped: {flows['subnets_tested']} of "
                           f"{flows['subnets_total']} subnet(s) tested — untested subnets are unverified")
    for f in flows["inconclusive"]:
        blind_spots.append(f"flow {f['src']} -> {f['dst']} inconclusive: {f['reason']}")
    for s in segmentation:
        if s["held"] == "not_evaluable":
            blind_spots.append(f"segmentation invariant not evaluable: {s['invariant']} — {s['evidence']}")
    for i in intents:
        if i.get("new_verdict") == "not_observed":
            blind_spots.append(f"path intent '{i.get('id')}' not observed after the change — "
                               "it cannot be re-certified")
    if intents_failed:
        blind_spots.append("path intents supplied but could not be evaluated — the catalog is unverified")

    # ---- verdict (the exact coverage-honest encoding) ----
    n_definitive = (flows["preserved"] + flows["both_unreachable"] + len(flows["changed"])
                    + sum(1 for s in segmentation if s["held"] in (True, False))
                    + sum(1 for i in intents if i.get("new_verdict") in ("pass", "fail")))
    if regressions:
        verdict = "FAIL"
        note = (f"{len(regressions)} regression(s): the candidate change demonstrably breaks the network — "
                "do not proceed. Each regression is cited below.")
    elif n_definitive == 0:
        verdict = "INDETERMINATE"
        note = ("nothing was definitively checkable across the pair — the certificate asserts NOTHING "
                "(this is not a pass; collect routes/segmentation evidence and re-run)")
    elif blind_spots:
        verdict = "CONDITIONAL"
        note = (f"no regressions across {n_definitive} definitive check(s), but {len(blind_spots)} named "
                "blind spot(s) remain open — clear or accept each before the window")
    else:
        verdict = "PASS"
        note = (f"all {n_definitive} definitive check(s) clean and no open blind spots "
                "(within the disclosed bounded sample)")

    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "verdict_note": note,
        "flows": flows,
        "segmentation": segmentation,
        "intents": intents,
        "regressions": regressions,
        "blind_spots": blind_spots,
        "stamps": {"before": _stamp(before), "after": _stamp(after)},
    }
