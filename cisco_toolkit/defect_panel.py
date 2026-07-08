"""Seeded-defect panel — the true-negative-rate (TNR) harness for the deliverable-QA judge (Move 1).

The feedback nerve's QA verdict is only trustworthy if the judge *rejects* known-bad deliverables. LLM
judges are documented to accept almost anything — Jain et al. (`arXiv:2510.11822`, "Beyond Consensus"):
true-positive rate > 96% but **true-negative rate < 25%** ("agreeableness bias") — so an all-APPROVE
scorecard is the *predicted* output of a broken instrument, not evidence of quality. This module builds a
reproducible panel of atomic, script-injected defects — **each a direct violation of a named doctrine
law** — so the judge's TNR can be MEASURED, not assumed.

Two representations, deliberately:
  * the STRUCTURED deliverable (carrying ground-truth flags like ``in_corpus`` / ``in_rib_fib``) — the
    answer-key oracle AND the bias-free **deterministic-arm** baseline (:func:`deterministic_findings`):
    a pure mechanical check catches the seeded defect with no LLM. This is the floor the judge must clear
    (an LLM verdict is only admissible where it agrees with / is dominated by this arm).
  * the TEXT rendering (:func:`render_text`, oracle flags stripped) — what the LLM judge actually sees; it
    must infer the violation from prose alone (e.g. that a "healthy" claim contradicts the coverage
    manifest). Only the subset visible in text (``detect == "both"``, :func:`text_visible_ids`) is a fair
    LLM-judge panel; the rest are deterministic-arm-only by construction.

Offline, pure-stdlib, no egress, no device contact. The panel is regenerable so a judge cannot memorize
it; the answer key is meant to be sealed (two-store) from the judge under test. This module is the
DETERMINISTIC substrate — wiring the injectors onto the engine's real generated deliverables, and running
a live cross-family judge over the text, are the follow-on steps; the defect *semantics* live here.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# --- the doctrine-mapped defect registry ------------------------------------------------------------
# Each defect violates a named law from the assessment doctrine (the SKILL/CLAUDE coverage-honesty +
# migration rules). ``detect`` = "both" when the violation is visible in the rendered deliverable text
# (a fair LLM-judge test); "deterministic" when catching it needs an oracle flag not present in the text
# (the engine's evidence) — those belong to the deterministic arm, never the LLM judge.
DEFECTS: Dict[str, Dict[str, str]] = {
    "D-01": {"class": "missing-rollback", "detect": "both",
             "law": "every MOP step carries a rollback + trigger",
             "desc": "a MOP step has no rollback stanza"},
    "D-02": {"class": "wrong-acl-direction", "detect": "deterministic",
             "law": "forwarding correctness != config presence",
             "desc": "ACL applied in the wrong direction vs the design"},
    "D-03": {"class": "phantom-health", "detect": "both",
             "law": "record UNKNOWN explicitly; no confidence theater",
             "desc": "'healthy' asserted over a device absent from the collection manifest"},
    "D-04": {"class": "unverified-redundancy", "detect": "deterministic",
             "law": "skeptical of apparent redundancy",
             "desc": "HSRP/VRRP 'verified' with only one peer in evidence"},
    "D-05": {"class": "unsupported-vlan", "detect": "deterministic",
             "law": "every finding traces to observed evidence",
             "desc": "a VLAN referenced but absent from any switchport/trunk evidence"},
    "D-06": {"class": "unsafe-sequence", "detect": "both",
             "law": "pre-checks precede irreversible actions",
             "desc": "an irreversible cutover step ordered before its verification"},
    "D-07": {"class": "fabricated-citation", "detect": "deterministic",
             "law": "never infer from memory",
             "desc": "a CLI citation whose evidence hash is not in the collected corpus"},
    "D-08": {"class": "stale-evidence", "detect": "deterministic",
             "law": "one source of truth",
             "desc": "evidence from a prior collection epoch presented as current"},
    "D-09": {"class": "matrix-twin-conflict", "detect": "deterministic",
             "law": "control-plane state != service health",
             "desc": "a failure-matrix survivability claim the failover twin contradicts"},
    "D-10": {"class": "unproven-route", "detect": "deterministic",
             "law": "route present != forwarding proven",
             "desc": "a static/bypass route asserted but absent from the RIB/FIB"},
    "D-11": {"class": "cross-artifact-mismatch", "detect": "both",
             "law": "workbook and runbook agree on every number",
             "desc": "workbook and runbook state different totals for the same thing"},
    "D-12": {"class": "empty-nrfu-evidence", "detect": "both",
             "law": "up/established is not healthy",
             "desc": "an NRFU item marked PASS with an empty captured-output field"},
}

DEFECT_IDS: Tuple[str, ...] = tuple(sorted(DEFECTS))


def text_visible_ids() -> Tuple[str, ...]:
    """The defects catchable by an LLM judge reading the deliverable TEXT (``detect == "both"``) — the
    only fair LLM-judge panel. The rest need an oracle flag absent from the text (deterministic-arm)."""
    return tuple(d for d in DEFECT_IDS if DEFECTS[d]["detect"] == "both")


def good_deliverable() -> Dict[str, Any]:
    """A clean, internally-consistent minimal deliverable draft — the panel's known-good baseline.
    :func:`deterministic_findings` returns ``set()`` on it (no false positives)."""
    return {
        "coverage_manifest": {"collected": ["sw1", "sw2"], "uncollected": ["core9"]},
        "mop_steps": [
            {"id": "M1", "action": "shut uplink Gi1/0/1", "rollback": "no shut Gi1/0/1",
             "irreversible": False, "order": 1},
            {"id": "M2", "action": "verify DR path reachable", "rollback": "n/a - verification step",
             "irreversible": False, "order": 2},
            {"id": "M3", "action": "withdraw BGP advertisement 10.0.0.0/24",
             "rollback": "re-advertise 10.0.0.0/24", "irreversible": True, "order": 3},
        ],
        "acl_rules": [{"name": "ACL-EDGE", "direction": "out", "required_direction": "out"}],
        "health_claims": [{"device": "sw1", "claim": "healthy"}],
        "redundancy_claims": [{"group": "HSRP-10", "verified": True, "peers_in_evidence": 2}],
        "vlan_refs": [{"vlan": 40, "in_switchport_evidence": True}],
        "citations": [{"text": "show version -> IOS-XE 17.9", "evidence_hash": "abc123",
                       "in_corpus": True, "epoch": "current"}],
        "failure_matrix": [{"scenario": "core9 down", "survivable": True, "twin_result": "survivable"}],
        "routes": [{"prefix": "0.0.0.0/0", "asserted": True, "in_rib_fib": True}],
        "totals": {"endpoints_workbook": 253, "endpoints_runbook": 253},
        "nrfu_items": [{"id": "N1", "status": "PASS",
                        "captured_output": "Gi1/0/1 up/up; 10.0.0.1 reachable"}],
    }


# --- injectors: each mutates exactly one thing to violate its law, and returns the location ----------

def _inj_01(d: Dict[str, Any]) -> str:
    d["mop_steps"][2]["rollback"] = ""                     # M3 (irreversible) loses its rollback
    return "mop_steps:M3"


def _inj_02(d: Dict[str, Any]) -> str:
    d["acl_rules"][0]["direction"] = "in"                  # design requires "out"
    return "acl_rules:ACL-EDGE"


def _inj_03(d: Dict[str, Any]) -> str:
    d["health_claims"].append({"device": "core9", "claim": "healthy"})   # core9 is uncollected
    return "health_claims:core9"


def _inj_04(d: Dict[str, Any]) -> str:
    d["redundancy_claims"][0]["peers_in_evidence"] = 1     # "verified" but only one peer seen
    return "redundancy_claims:HSRP-10"


def _inj_05(d: Dict[str, Any]) -> str:
    d["vlan_refs"][0]["in_switchport_evidence"] = False    # referenced, no switchport evidence
    return "vlan_refs:40"


def _inj_06(d: Dict[str, Any]) -> str:
    d["mop_steps"][2]["order"] = 0                         # the irreversible withdraw now precedes verify
    return "mop_steps:M3"


def _inj_07(d: Dict[str, Any]) -> str:
    d["citations"][0]["in_corpus"] = False                 # hash not in the collected corpus
    return "citations:abc123"


def _inj_08(d: Dict[str, Any]) -> str:
    d["citations"][0]["epoch"] = "prior-2025Q1"            # stale epoch presented as current
    return "citations:abc123"


def _inj_09(d: Dict[str, Any]) -> str:
    d["failure_matrix"][0]["twin_result"] = "not_survivable"   # claim survivable; twin disagrees
    return "failure_matrix:core9 down"


def _inj_10(d: Dict[str, Any]) -> str:
    d["routes"].append({"prefix": "10.9.9.0/24", "asserted": True, "in_rib_fib": False})
    return "routes:10.9.9.0/24"


def _inj_11(d: Dict[str, Any]) -> str:
    d["totals"]["endpoints_runbook"] = 250                 # workbook says 253
    return "totals"


def _inj_12(d: Dict[str, Any]) -> str:
    d["nrfu_items"][0]["captured_output"] = ""             # PASS with no captured output
    return "nrfu_items:N1"


_INJECTORS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "D-01": _inj_01, "D-02": _inj_02, "D-03": _inj_03, "D-04": _inj_04, "D-05": _inj_05,
    "D-06": _inj_06, "D-07": _inj_07, "D-08": _inj_08, "D-09": _inj_09, "D-10": _inj_10,
    "D-11": _inj_11, "D-12": _inj_12,
}


def inject(defect_id: str, base: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Return ``(corrupted_deliverable, answer_key)`` for one defect. Pure: deep-copies the base, mutates
    exactly one thing, and records where. The key is ``{defect_id, defect_class, location, law}`` — seal
    it from the judge under test. Raises ``KeyError`` on an unknown id."""
    if defect_id not in DEFECTS:
        raise KeyError(f"unknown defect id: {defect_id!r}")
    d = copy.deepcopy(base if base is not None else good_deliverable())
    loc = _INJECTORS[defect_id](d)
    meta = DEFECTS[defect_id]
    return d, {"defect_id": defect_id, "defect_class": meta["class"], "location": loc, "law": meta["law"]}


# --- the deterministic arm: mechanical detection over the structured form (oracle + bias-free floor) --

def deterministic_findings(d: Dict[str, Any]) -> Set[str]:
    """The defect ids a pure mechanical check detects in the STRUCTURED deliverable (using its oracle
    flags). No LLM, no egress — the bias-free floor and the answer-key oracle. Returns ``set()`` on a
    clean deliverable (no false positives)."""
    found: Set[str] = set()
    uncollected = set((d.get("coverage_manifest") or {}).get("uncollected", []))

    for s in d.get("mop_steps", []):
        if not str(s.get("rollback", "")).strip():
            found.add("D-01")
    for a in d.get("acl_rules", []):
        if a.get("direction") != a.get("required_direction"):
            found.add("D-02")
    for h in d.get("health_claims", []):
        if h.get("device") in uncollected and str(h.get("claim", "")).lower() in ("healthy", "redundant"):
            found.add("D-03")
    for r in d.get("redundancy_claims", []):
        if r.get("verified") and int(r.get("peers_in_evidence", 0) or 0) < 2:
            found.add("D-04")
    for v in d.get("vlan_refs", []):
        if not v.get("in_switchport_evidence", False):
            found.add("D-05")
    steps = d.get("mop_steps", [])
    irrev = [s.get("order", 0) for s in steps if s.get("irreversible")]
    verify = [s.get("order", 0) for s in steps if "verify" in str(s.get("action", "")).lower()]
    if irrev and verify and min(irrev) < max(verify):
        found.add("D-06")
    for c in d.get("citations", []):
        if not c.get("in_corpus", False):
            found.add("D-07")
        if str(c.get("epoch", "current")).strip().lower() != "current":
            found.add("D-08")
    for m in d.get("failure_matrix", []):
        if m.get("survivable") and m.get("twin_result") == "not_survivable":
            found.add("D-09")
    for rt in d.get("routes", []):
        if rt.get("asserted") and not rt.get("in_rib_fib", False):
            found.add("D-10")
    t = d.get("totals") or {}
    if t.get("endpoints_workbook") != t.get("endpoints_runbook"):
        found.add("D-11")
    for n in d.get("nrfu_items", []):
        if str(n.get("status", "")).upper() == "PASS" and not str(n.get("captured_output", "")).strip():
            found.add("D-12")
    return found


# --- the text rendering: what the LLM judge sees (oracle flags stripped) -----------------------------

def render_text(d: Dict[str, Any]) -> str:
    """Render the deliverable to the prose an LLM judge reads. Deliberately OMITS the oracle flags
    (``in_corpus`` / ``in_rib_fib`` / ``required_direction`` / ``twin_result`` / ``peers_in_evidence`` /
    ``in_switchport_evidence`` / ``epoch``) so a text-only judge must infer a violation from the claims
    and their cross-references (e.g. a 'healthy' device that the coverage line lists as not collected)."""
    mani = d.get("coverage_manifest") or {}
    L: List[str] = ["COVERAGE: collected " + ", ".join(mani.get("collected", []))
                    + "; NOT collected " + ", ".join(mani.get("uncollected", [])) + "."]
    L.append("MOP STEPS (in order):")
    for s in sorted(d.get("mop_steps", []), key=lambda x: x.get("order", 0)):
        L.append(f"  [{s.get('order')}] {s.get('id')}: {s.get('action')}. "
                 f"rollback: {s.get('rollback') or '(none)'}")
    for a in d.get("acl_rules", []):
        L.append(f"ACL {a.get('name')} applied {a.get('direction')}bound.")
    for h in d.get("health_claims", []):
        L.append(f"Device {h.get('device')} assessed: {h.get('claim')}.")
    for r in d.get("redundancy_claims", []):
        L.append(f"Redundancy {r.get('group')}: {'verified' if r.get('verified') else 'unverified'}.")
    for v in d.get("vlan_refs", []):
        L.append(f"VLAN {v.get('vlan')} is in scope for migration.")
    for c in d.get("citations", []):
        L.append(f"Evidence: {c.get('text')} [hash {c.get('evidence_hash')}].")
    for m in d.get("failure_matrix", []):
        L.append(f"Failure scenario '{m.get('scenario')}': "
                 f"{'survivable' if m.get('survivable') else 'NOT survivable'}.")
    for rt in d.get("routes", []):
        L.append(f"Route {rt.get('prefix')} present in the design.")
    t = d.get("totals") or {}
    L.append(f"Endpoint total: {t.get('endpoints_workbook')} (workbook) / "
             f"{t.get('endpoints_runbook')} (runbook).")
    for n in d.get("nrfu_items", []):
        L.append(f"NRFU {n.get('id')}: {n.get('status')}. captured output: "
                 f"{n.get('captured_output') or '(empty)'}")
    return "\n".join(L)


# --- panel assembly + scoring ------------------------------------------------------------------------

def build_panel(ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Build the panel: one entry per defect id (default: all 12). Each entry is
    ``{defect_id, structured, text, key}`` — ``text`` is fed to the judge, ``key`` is sealed and passed
    only to :func:`score_verdicts`."""
    out: List[Dict[str, Any]] = []
    for did in (ids if ids is not None else list(DEFECT_IDS)):
        corrupted, key = inject(did)
        out.append({"defect_id": did, "structured": corrupted, "text": render_text(corrupted), "key": key})
    return out


def score_verdicts(verdicts: List[Dict[str, Any]], keys: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Score judge verdicts against the sealed answer keys. ``verdicts`` is a list of
    ``{defect_id, verdict, defect_class?}``; a REJECT/BLOCK/FAIL naming the CORRECT defect class scores as
    a *localized* true-negative. Returns localized TNR (the headline), the raw rejection rate, and the
    *unlocalized-rejection rate* — a judge that rejects everything for the wrong reason is also broken."""
    n = len(keys)
    by_id: Dict[str, Dict[str, Any]] = {}
    for v in verdicts:
        vid = v.get("defect_id") or v.get("artifact_id")
        if vid is not None:
            by_id[vid] = v
    localized = 0
    rejected = 0
    per: Dict[str, Dict[str, bool]] = {}
    for did, key in keys.items():
        v = by_id.get(did, {})
        is_reject = str(v.get("verdict", "")).strip().upper() in ("REJECT", "BLOCK", "FAIL", "NOT_READY")
        class_ok = v.get("defect_class") == key["defect_class"]
        if is_reject:
            rejected += 1
        if is_reject and class_ok:
            localized += 1
        per[did] = {"rejected": is_reject, "class_correct": bool(class_ok)}
    return {
        "n": n,
        "localized_tnr": round(localized / n, 3) if n else None,
        "rejection_rate": round(rejected / n, 3) if n else None,
        "unlocalized_rejection_rate": round((rejected - localized) / n, 3) if n else None,
        "per_defect": per,
    }


def deterministic_baseline(ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """The deterministic arm as a 'judge': for each seeded defect, does the mechanical check catch it
    (and only it)? This is the bias-free floor the LLM judge must clear. TNR here is 1.0 by construction
    for the structured oracle — reported so the harness has a self-check that the injectors and detector
    stay in agreement."""
    panel = build_panel(ids)
    verdicts: List[Dict[str, Any]] = []
    for entry in panel:
        found = deterministic_findings(entry["structured"])
        did = entry["defect_id"]
        # the deterministic arm 'rejects' iff it finds exactly the seeded defect; class = the defect class
        hit = did in found
        verdicts.append({"defect_id": did, "verdict": "REJECT" if hit else "APPROVE",
                         "defect_class": DEFECTS[did]["class"] if hit else None})
    keys = {e["defect_id"]: e["key"] for e in panel}
    return score_verdicts(verdicts, keys)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. ``--baseline`` prints the deterministic-arm TNR over the full panel (the floor); ``--render
    <D-XX>`` prints one corrupted deliverable's judge-visible text; ``--list`` prints the registry.
    Reads only; no egress, no device contact."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--list" in argv:
        for did in DEFECT_IDS:
            m = DEFECTS[did]
            print(f"{did}  [{m['detect']:<13}] {m['class']:<24} — {m['desc']} (law: {m['law']})")
        return 0
    if "--render" in argv:
        i = argv.index("--render")
        did = argv[i + 1] if i + 1 < len(argv) else ""
        if did not in DEFECTS:
            print(f"unknown defect id {did!r}; try one of {', '.join(DEFECT_IDS)}")
            return 2
        corrupted, key = inject(did)
        print(f"# seeded {did} ({key['defect_class']}) at {key['location']} — sealed from the judge\n")
        print(render_text(corrupted))
        return 0
    base = deterministic_baseline()
    print(f"deterministic-arm baseline over the {base['n']}-defect panel: "
          f"localized TNR = {base['localized_tnr']} (the floor the LLM judge must clear)")
    print(f"LLM-judge fair panel (text-visible): {', '.join(text_visible_ids())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
