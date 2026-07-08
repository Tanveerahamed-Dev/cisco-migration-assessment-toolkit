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

**Reliable structured verdicts.** Ollama *structured outputs* (a JSON schema in ``format``) constrain the
model to emit ``{reasoning, verdict, defect_class}`` with ``verdict``/``defect_class`` as ENUMS — so the
judge can reason (refute-first) yet still return a parseable, localized answer. ``think: false`` suppresses
the slow chain-of-thought block that makes small models time out on a CPU host.

**Hardware note (measured):** an 8B model swaps on a 16 GB CPU-only host (~7 min/call, timeouts); ``qwen3:4b``
fits with headroom (~80 s/call). The default reflects that.

**Graceful + hermetic.** If Ollama is not listening, :func:`run_baseline` returns ``{ok: False, reason}`` and
never hangs or raises. The parser and prompt builder are pure and unit-tested; the Ollama call is injectable,
so the test suite never requires a running model.

Usage: ``python ollama_judge.py qwen3:4b``  →  prints the judge's measured localized TNR over the panel.
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
DEFAULT_MODEL = os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3:4b")   # 8b swaps on a 16GB CPU host; 4b fits


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


def judge_schema(classes: Optional[List[str]] = None) -> Dict[str, Any]:
    """The Ollama structured-output schema. ``reasoning`` FIRST (so the model reasons before committing),
    then ``verdict`` and ``defect_class`` as enums (so the answer is always valid + localizable)."""
    cls = list(classes if classes is not None else _text_visible_classes()) + ["NONE"]
    return {"type": "object",
            "properties": {"reasoning": {"type": "string"},
                           "verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                           "defect_class": {"type": "string", "enum": cls}},
            "required": ["reasoning", "verdict", "defect_class"]}


def build_prompt(deliverable_text: str, classes: Optional[List[str]] = None) -> str:
    """The refute-first judge prompt: a skeptical, coverage-honest reviewer told to DISPROVE the excerpt.
    Output shape is enforced by :func:`judge_schema`; the prompt supplies the rules + the class vocabulary."""
    vocab = ", ".join(classes if classes is not None else _text_visible_classes())
    return (
        "You are an INDEPENDENT, skeptical senior Cisco network reviewer performing adversarial QA on ONE\n"
        "migration-deliverable excerpt. Your job is to try to DISPROVE it. Apply coverage-honesty:\n"
        "- \"not observed\" / \"not collected\" is NOT \"healthy\": a health or redundancy claim about a\n"
        "  device the COVERAGE line says was NOT collected is a defect (class 'phantom-health').\n"
        "- a MOP step with no rollback is a defect ('missing-rollback'); an IRREVERSIBLE step (e.g.\n"
        "  withdrawing a BGP advertisement) ordered BEFORE its verification step is a defect ('unsafe-sequence').\n"
        "- the workbook and the runbook must agree on every number; different totals are 'cross-artifact-mismatch'.\n"
        "- an NRFU item marked PASS with an EMPTY captured-output field is 'empty-nrfu-evidence'.\n"
        "Find the SPECIFIC evidence that makes this deliverable WRONG. Give brief reasoning, then a verdict\n"
        f"(APPROVE only if you find nothing wrong; else REJECT) and the single defect class (one of: {vocab};\n"
        "or NONE if APPROVE).\n\n"
        "DELIVERABLE:\n"
        f"{deliverable_text}\n"
    )


def parse_verdict(text: str) -> Dict[str, Any]:
    """Parse a judge's answer into ``{verdict, defect_class}``. Tries structured JSON first (the normal path
    under ``format``), then falls back to free-text regex. Conservative: only a CLEAR reject counts; a reject
    localizes only on a KNOWN class (an unlocalized / garbled reject stays class-None; empty -> APPROVE)."""
    t = text or ""
    known = {meta["class"] for meta in P.DEFECTS.values()}
    # --- structured path ---
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and "verdict" in obj:
            verdict = "REJECT" if str(obj.get("verdict", "")).upper().startswith(
                ("REJECT", "BLOCK", "FAIL")) else "APPROVE"
            dc = str(obj.get("defect_class") or "").strip()
            defect_class = dc if (verdict == "REJECT" and dc in known) else None
            return {"verdict": verdict, "defect_class": defect_class}
    except Exception:
        pass
    # --- free-text fallback ---
    up = t.upper()
    m = re.search(r"VERDICT\s*[:=]\s*(APPROVE\w*|REJECT\w*|BLOCK\w*|FAIL\w*)", up)
    token = m.group(1) if m else ("REJECT" if re.search(r"\b(REJECT|BLOCK|FAIL)", up) else "APPROVE")
    verdict = "REJECT" if token.startswith(("REJECT", "BLOCK", "FAIL")) else "APPROVE"
    defect_class = None
    if verdict == "REJECT":
        cm = re.search(r"DEFECT[_ ]?CLASS\s*[:=]\s*([A-Za-z][\w -]+)", t, re.I)
        if cm:
            cand = cm.group(1).strip().lower().replace(" ", "-")
            for c in known:
                if c.lower() == cand:
                    defect_class = c
                    break
    return {"verdict": verdict, "defect_class": defect_class}


def _chat(model: str, prompt: str, *, timeout: int = 420, fmt: Optional[Dict[str, Any]] = None) -> str:
    """One completion via the LOCAL Ollama chat API. ``urllib`` is imported lazily and this file is outside
    the ``cisco_toolkit/`` fence, so the engine's no-egress import graph is untouched. ``think: false`` skips
    the slow chain-of-thought block; ``keep_alive`` holds the model resident across a multi-defect run on a
    memory-tight CPU host; ``fmt`` (a JSON schema) forces structured, parseable output."""
    import urllib.request                                       # localhost only; outside the cisco_toolkit fence
    body: Dict[str, Any] = {
        "model": model, "stream": False, "keep_alive": "15m", "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_predict": 640}}     # deterministic; bounded so it can't run away
    if fmt is not None:
        body["format"] = fmt                                   # ollama structured output -> a valid JSON verdict
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
    """Run the cross-family judge over the text-visible defect panel and score it against the sealed key.
    ``chat`` / ``listening`` are injectable for hermetic tests (default: the real Ollama with the structured
    schema). Returns ``{ok: False, reason}`` when Ollama is down (never raises).

    Two headline metrics: ``rejection_rate`` (did it catch the bad work at all — the veto signal an ensemble
    needs) and ``localized_tnr`` (did it catch AND correctly name the defect — the stricter diagnostic bar)."""
    probe = listening if listening is not None else _listening
    if not probe(host):
        return {"ok": False, "reason": f"Ollama not listening on {host} — pull the model and start Ollama"}
    classes = _text_visible_classes()
    schema = judge_schema(classes)
    do_chat = chat if chat is not None else (lambda prompt: _chat(model, prompt, fmt=schema))
    ids = list(ids) if ids is not None else list(P.text_visible_ids())
    panel = P.build_panel(ids)
    keys = {e["defect_id"]: e["key"] for e in panel}
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
    print(f"  rejection rate       = {res['rejection_rate']}   (caught the bad work at all — the veto signal)")
    print(f"  localized TNR        = {res['localized_tnr']}   (rejected WITH the right defect class)")
    print(f"  unlocalized rejects  = {res['unlocalized_rejection_rate']}   (rejected, wrong/'no' class)")
    for v in res["verdicts"]:
        print(f"    {v['defect_id']}: {v['verdict']:<7} class={v['defect_class']}")
    print("  (the deterministic arm catches all 12 by construction; this is the LLM judge's floor to clear)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
