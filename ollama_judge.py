"""Cross-family LLM-as-judge over a LOCAL Ollama — the debiased QA judge's non-Claude arm (Move 1).

Lives at the repo ROOT, **outside** ``cisco_toolkit/`` — exactly like :mod:`ollama_recall` — so its
``urllib``/Ollama use never trips the no-egress attestation (which forbids network libraries anywhere in
``cisco_toolkit/`` at any depth). It talks only to a **local** Ollama on 127.0.0.1:11434 (an on-host
service, not the network), so the air-gapped repo's reproducibility is unchanged.

**Why a non-Claude judge.** A Claude judge on Claude-authored work shares failure modes — self-preference
and the fact that "great models think alike" (`arXiv:2502.04313`) — and defaults to *agreeableness*
(accept-everything: Jain et al. `2510.11822`, true-negative rate < 25%). A different model **family**
(Qwen / Llama / Gemma via Ollama) is cross-family, air-gapped, and $0 — the minority-veto arm the plan
needs. This module runs that judge over the seeded-defect panel (:mod:`cisco_toolkit.defect_panel`) and
**MEASURES its true-negative rate** against the sealed answer key.

**Refute-first.** The judge is told to find the specific evidence that makes the deliverable WRONG before
any APPROVE — because majority-vote does NOT fix agreeableness (Jain), a refute-first + veto stance does.

**Graceful + hermetic.** If Ollama is not listening, :func:`run_baseline` returns ``{ok: False, reason}``
and never hangs (fast-fails on a closed port) or raises. The verdict PARSER and the prompt BUILDER are pure
and unit-tested; the Ollama call is injectable, so the test suite never requires a running model.

Usage: ``python ollama_judge.py qwen3:8b``  →  prints the judge's measured localized TNR over the panel.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
from typing import Any, Callable, Dict, List, Optional

from cisco_toolkit import defect_panel as P

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3:8b")


def _listening(hostport: str = OLLAMA_HOST, *, timeout: float = 0.4) -> bool:
    """Fast TCP probe — is a local Ollama actually up? Degrade in < 0.5s when it isn't."""
    try:
        host, _, port = hostport.partition(":")
        with socket.create_connection((host or "127.0.0.1", int(port or "11434")), timeout=timeout):
            return True
    except Exception:
        return False


def _text_visible_classes() -> List[str]:
    """The defect classes an LLM judge could legitimately cite from the deliverable text (detect=='both')."""
    return [P.DEFECTS[d]["class"] for d in P.text_visible_ids()]


def build_prompt(deliverable_text: str, classes: Optional[List[str]] = None) -> str:
    """The refute-first judge prompt: a skeptical, coverage-honest reviewer told to DISPROVE the excerpt
    first, then answer in a parseable two-line verdict. ``classes`` is the vocabulary it may cite."""
    vocab = ", ".join(classes if classes is not None else _text_visible_classes())
    return (
        "You are an INDEPENDENT, skeptical senior Cisco network reviewer performing adversarial QA on ONE\n"
        "migration-deliverable excerpt. Your job is to try to DISPROVE it. Apply coverage-honesty:\n"
        "- \"not observed\" / \"not collected\" is NOT \"healthy\": a health or redundancy claim about a\n"
        "  device the COVERAGE line says was NOT collected is a defect.\n"
        "- every claim must trace to observed evidence.\n"
        "- a MOP step with no rollback is a defect; an IRREVERSIBLE step (e.g. withdrawing a BGP\n"
        "  advertisement) placed BEFORE its verification step is a defect.\n"
        "- the workbook and the runbook must agree on every number; different totals are a defect.\n"
        "- an NRFU item marked PASS with an EMPTY captured-output field is a defect.\n"
        "First find the SPECIFIC evidence that makes this deliverable WRONG. APPROVE only if you cannot.\n"
        "Answer on the FINAL TWO LINES, exactly:\n"
        "VERDICT: <APPROVE or REJECT>\n"
        f"DEFECT_CLASS: <one of: {vocab} — or NONE if APPROVE>\n\n"
        "DELIVERABLE:\n"
        f"{deliverable_text}\n"
    )


def parse_verdict(text: str) -> Dict[str, Any]:
    """Parse a judge's free-text answer into ``{verdict, defect_class}``. Conservative: only a CLEAR reject
    counts (garbled / empty / hedged -> APPROVE, i.e. the defect slipped through); ``defect_class`` is set
    only when an explicit ``DEFECT_CLASS:`` names a KNOWN class (an unlocalized reject stays class-None)."""
    t = text or ""
    up = t.upper()
    m = re.search(r"VERDICT\s*[:=]\s*(APPROVE\w*|REJECT\w*|BLOCK\w*|FAIL\w*)", up)
    token = m.group(1) if m else ("REJECT" if re.search(r"\b(REJECT|BLOCK|FAIL)", up) else "APPROVE")
    verdict = "REJECT" if token.startswith(("REJECT", "BLOCK", "FAIL")) else "APPROVE"
    defect_class: Optional[str] = None
    if verdict == "REJECT":
        known = {meta["class"] for meta in P.DEFECTS.values()}
        cm = re.search(r"DEFECT[_ ]?CLASS\s*[:=]\s*([A-Za-z][\w -]+)", t, re.I)
        if cm:
            cand = cm.group(1).strip().lower().replace(" ", "-")
            for c in known:
                if c.lower() == cand:
                    defect_class = c
                    break
    return {"verdict": verdict, "defect_class": defect_class}


def _chat(model: str, prompt: str, *, timeout: int = 120) -> str:
    """One completion via the LOCAL Ollama chat API. ``urllib`` is imported lazily and this file is outside
    the ``cisco_toolkit/`` fence, so the engine's no-egress import graph is untouched."""
    import urllib.request                                       # localhost only; outside the cisco_toolkit fence
    body = {"model": model, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0}}                      # deterministic judging
    req = urllib.request.Request(
        f"http://{OLLAMA_HOST}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 (localhost, opt-in)
        obj = json.load(r)
    return str((obj.get("message") or {}).get("content", "") or "")


def run_baseline(model: str = DEFAULT_MODEL, ids: Optional[List[str]] = None, *,
                 chat: Optional[Callable[[str], str]] = None,
                 listening: Optional[Callable[[str], bool]] = None,
                 host: str = OLLAMA_HOST) -> Dict[str, Any]:
    """Run the cross-family judge over the text-visible defect panel and score its localized TNR against
    the sealed key. ``chat`` / ``listening`` are injectable for hermetic tests (default: the real Ollama).
    Returns ``{ok: False, reason}`` when Ollama is down (never raises)."""
    probe = listening if listening is not None else _listening
    if not probe(host):
        return {"ok": False, "reason": f"Ollama not listening on {host} — pull the model and start Ollama"}
    do_chat = chat if chat is not None else (lambda prompt: _chat(model, prompt))
    ids = list(ids) if ids is not None else list(P.text_visible_ids())
    panel = P.build_panel(ids)
    keys = {e["defect_id"]: e["key"] for e in panel}
    classes = _text_visible_classes()
    verdicts: List[Dict[str, Any]] = []
    for e in panel:
        try:
            raw = do_chat(build_prompt(e["text"], classes))
        except Exception as ex:                                # a judge error = defect not caught (APPROVE)
            raw = f"(judge error: {ex})"
        v = parse_verdict(raw)
        verdicts.append({"defect_id": e["defect_id"], "verdict": v["verdict"],
                         "defect_class": v["defect_class"]})
    score = P.score_verdicts(verdicts, keys)
    return {"ok": True, "model": model, "verdicts": verdicts, **score}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    model = argv[0] if argv else DEFAULT_MODEL
    res = run_baseline(model)
    if not res.get("ok"):
        print(f"[ollama-judge] {res.get('reason')}")
        return 0                                               # graceful: nothing measured, not an error
    print(f"[ollama-judge] model={res['model']}  panel={res['n']} text-visible defects")
    print(f"  localized TNR        = {res['localized_tnr']}   (fraction rejected WITH the right defect class)")
    print(f"  raw rejection rate   = {res['rejection_rate']}")
    print(f"  unlocalized rejects  = {res['unlocalized_rejection_rate']}   (rejected for the wrong reason)")
    for v in res["verdicts"]:
        print(f"    {v['defect_id']}: {v['verdict']:<7} class={v['defect_class']}")
    print("  (the deterministic arm catches all 12 by construction; this is the LLM judge's floor to clear)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
