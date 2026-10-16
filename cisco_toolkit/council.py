"""Grounded ``/council`` — independent, refute-first, majority verifier lenses (Phase 3, D8).

A council checks a consequential claim with **N independent verifier lenses** and takes the **majority**.
Decision **D8**: the lenses are *independent and separately-contexted* (a lens never sees another's view),
**refute-first** (each tries to DISPROVE the claim and defaults to REFUTE when it cannot verify), and
aggregated by **majority — NO debate / no cross-critique** (debate underperforms independent-sample
majority; deliberation erased up to 72% of critical facts). This is the proposer≠verifier doctrine widened
to a panel.

For a domain-touching claim the lenses are the **domain packs** selected by the snapshot's
``architecture_coverage`` (:mod:`cisco_toolkit.domain_packs`) — the DC lens shows up iff ACI/overlay/Arista
is in the evidence, etc. When no domain pack applies, the council falls back to an **N-sample general
evidence lens** (self-consistency majority) so a council is always a real panel, never a single opinion.

Two pure, testable pieces:

- :func:`plan_council` — pick the lenses and build each one's refute-first, evidence-grounded prompt.
- :func:`aggregate` — the refute-first majority over the lenses' returned verdicts.

The actual spawning of independent, separately-contexted lenses is the orchestrator's job (the
``/council`` command uses the Agent tool); this module holds only the selection + the aggregation, so the
load-bearing logic is unit-tested without any model call. Refute-first is **fail-safe**: no support-majority
(including all-uncertain or a zero-lens council) blocks the consequential output.
"""
from __future__ import annotations

from typing import Any, Dict, List

from cisco_toolkit.domain_packs import select_packs

SUPPORT, REFUTE, UNCERTAIN = "SUPPORT", "REFUTE", "UNCERTAIN"


def _lens_prompt(title: str, doc: str, claim: str) -> str:
    """A refute-first, independent, evidence-grounded lens prompt."""
    return (
        f"You are the '{title}' verifier LENS on a council. Work INDEPENDENTLY — you cannot see any "
        f"other lens's verdict; do not deliberate, defer, or reconcile with anyone. Your task is to try "
        f"to REFUTE the claim, grounded in {doc}'s review checklist and the collected snapshot evidence: "
        f"cite the field/line, never infer state from memory. If you cannot verify the claim against "
        f"evidence, return REFUTE — refute-first ('not observed' is never 'healthy'). "
        f"CLAIM: \"{claim}\". Output exactly two lines: 'VERDICT=<SUPPORT|REFUTE|UNCERTAIN>' then one "
        f"line with your strongest counterexample (or the cited evidence that supports it)."
    )


def plan_council(claim: str, coverage: Any, *, min_lenses: int = 1,
                 general_samples: int = 3) -> Dict[str, Any]:
    """Select the council's lenses for ``claim`` given the snapshot's ``architecture_coverage``.

    Domain-touching claims get the coverage-selected domain packs as lenses (findings-carrying packs first).
    If fewer than ``min_lenses`` domain lenses apply, fall back to ``general_samples`` independent copies of
    a general evidence lens (an N-sample self-consistency majority). Pure — no model call, no I/O."""
    sel = select_packs(coverage)
    # findings-carrying packs first — those lenses have the most to check.
    ordered = sorted(sel["selected"], key=lambda s: (not s["with_findings"]))
    lenses: List[Dict[str, Any]] = [
        {"lens": s["pack"], "title": s["title"], "doc": s["doc"],
         "prompt": _lens_prompt(s["title"], s["doc"], claim),
         "priority": bool(s["with_findings"])}
        for s in ordered
    ]
    if len(lenses) < min_lenses:
        for i in range(max(1, general_samples)):
            lenses.append({"lens": f"general#{i + 1}", "title": "General evidence",
                           "doc": "the snapshot evidence + docs/ssot.md",
                           "prompt": _lens_prompt("General evidence",
                                                  "the snapshot evidence + docs/ssot.md", claim),
                           "priority": False})
    return {"claim": claim, "lenses": lenses, "n": len(lenses),
            "protocol": ("independent, separately-contexted, refute-first lenses; majority; "
                         "NO debate / no cross-critique (D8)")}


def normalize_verdict(v: Any) -> str:
    """Coerce a lens's free-text verdict to SUPPORT / REFUTE / UNCERTAIN (refute-first on ambiguity)."""
    s = str(v).strip().upper()
    if REFUTE in s or "BLOCK" in s or "REJECT" in s or "DISPROVE" in s:
        return REFUTE
    if SUPPORT in s or "APPROVE" in s or "CONFIRM" in s or s in ("PASS", "TRUE"):
        return SUPPORT
    return UNCERTAIN


def aggregate(verdicts: List[Any], *, refute_first: bool = True) -> Dict[str, Any]:
    """Refute-first majority over the lenses' verdicts (D8). SUPPORT **only** on a strict majority of ALL
    lenses; anything short of that — a tie, an uncertain plurality, or a zero-lens council — blocks the
    consequential output (REFUTE). No debate: verdicts are counted, never reconciled. Returns the council
    verdict, the tally, and the count of refuters (the counterexamples to read)."""
    norm = [normalize_verdict(v) for v in (verdicts or [])]
    n = len(norm)
    support, refute, uncertain = norm.count(SUPPORT), norm.count(REFUTE), norm.count(UNCERTAIN)
    if n == 0:
        return {"verdict": REFUTE if refute_first else UNCERTAIN, "n": 0, "support": 0,
                "refute": 0, "uncertain": 0,
                "rationale": "no lens returned a verdict — cannot certify (refute-first fail-safe)"}
    if support * 2 > n:
        verdict, rationale = SUPPORT, f"{support}/{n} lenses support (strict majority)"
    elif refute_first:
        verdict = REFUTE
        rationale = (f"no support-majority ({support}/{n}) — refute-first blocks the consequential output "
                     f"(refute={refute}, uncertain={uncertain})")
    else:
        verdict = SUPPORT if support >= refute else REFUTE
        rationale = f"plurality vote (support={support}, refute={refute}, uncertain={uncertain})"
    return {"verdict": verdict, "n": n, "support": support, "refute": refute,
            "uncertain": uncertain, "rationale": rationale}


def render_plan(plan: Dict[str, Any]) -> str:
    L = [f"/council on: \"{plan['claim']}\"  ({plan['n']} independent lens(es); {plan['protocol']})"]
    for le in plan["lenses"]:
        L.append(f"  [{le['lens']}] {le['title']}" + ("  (findings — priority)" if le["priority"] else ""))
    return "\n".join(L)


def main(argv: List[str] = None) -> int:
    """CLI glue for the ``/council`` command (the orchestrator does the independent spawning):

      python -m cisco_toolkit.council plan "<claim>" <snapshot.json>   # emit the lens plan (JSON)
      python -m cisco_toolkit.council aggregate SUPPORT REFUTE …       # refute-first majority verdict
    """
    import json
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv and argv[0] == "plan":
        claim = argv[1] if len(argv) > 1 else ""
        snap_path = argv[2] if len(argv) > 2 else ""
        coverage: Any = {}
        if snap_path:
            try:
                snap = json.load(open(snap_path, encoding="utf-8"))
                coverage = snap.get("architecture_coverage")
                if not isinstance(coverage, dict):
                    from cisco_toolkit.design_advisor import compute_architecture_coverage
                    coverage = compute_architecture_coverage(snap)
            except Exception as e:
                print(f"could not read/compute coverage: {e!r}", file=sys.stderr)
        print(json.dumps(plan_council(claim, coverage), ensure_ascii=True, indent=1))
        return 0
    if argv and argv[0] == "aggregate":
        res = aggregate(argv[1:])
        print(json.dumps(res, ensure_ascii=True))
        return 0 if res["verdict"] == SUPPORT else 3   # exit 3 = not certified (refute-first)
    print(main.__doc__.strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
