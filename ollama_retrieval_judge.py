"""Local-Ollama grader for the D10 Phase-2 retrieval eval (P2-2) — the judge's I/O shell.

Lives at the repo ROOT — deliberately **outside** ``cisco_toolkit/`` — so its ``socket``/``urllib``
use never trips the no-egress attestation (which forbids network libraries anywhere in
``cisco_toolkit/`` at any nesting depth). It talks only to a **local** Ollama on 127.0.0.1:11434
(on-host compute — ADR-0001 Amendment 1), invoked as a SUBPROCESS by
:func:`cisco_toolkit.retrieval_eval.invoke_judge_helper`, exactly like ``ollama_recall.py`` /
``graph_rank``.

This file is a THIN shell on purpose: the prompts, the structured-output schema and the
take-the-MIN dual-prompt combination are :mod:`cisco_toolkit.retrieval_eval`'s PURE functions
(one implementation, hermetically tested there); the sealed anchor key is never seen here — the
payload carries only pid/query/doc/excerpt/rubric, and the gate scoring happens in the caller
(the defect_panel separation).

Protocol: ``python ollama_retrieval_judge.py --pairs <payload.json> [--model M]`` reads
``{"pairs": [{pid, query, doc, excerpt, rubric}], "passes": N}`` and prints ONE json object:
``{"ok": true, "model": M, "grades": [{"pid": …, "final_by_pass": [g, …], "detail": […]}]}``.
Each pass grades every pair with BOTH prompts (neutral + adversarial, temperature 0) and records
the MIN. Ollama not listening → ``{"ok": false, "reason": …}`` fast (the caller records
signal_absent — a grade is never fabricated). Determinism note: temperature 0 makes repeat passes
*mostly* identical, not guaranteed — which is exactly what the §6 self-consistency κ measures.

Model default mirrors :mod:`ollama_judge` (``qwen3:4b`` — an 8B swaps on a 16 GB CPU host);
override with ``--model`` or ``OLLAMA_JUDGE_MODEL``.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any, Dict, List, Optional

from cisco_toolkit.retrieval_eval import combine_dual, judge_prompts, judge_schema

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3:4b")


def _listening(hostport: str = OLLAMA_HOST, *, timeout: float = 0.4) -> bool:
    """Fast TCP probe — degrade in <0.5s when no local Ollama is up (the ollama_judge idiom)."""
    try:
        host, _, port = hostport.partition(":")
        with socket.create_connection((host or "127.0.0.1", int(port or "11434")), timeout=timeout):
            return True
    except Exception:
        return False


def _chat(model: str, prompt: str, *, timeout: int = 300) -> str:
    """One structured completion via the LOCAL Ollama chat API (lazy ``urllib``, outside the
    fence): temperature 0, bounded output, ``think`` off, grade schema enforced. ``num_predict``
    1024: the adversarial prompt's reasoning-first output overran a 512 budget in the synthetic
    probe (truncated mid-JSON → unparseable → an honest None) — the budget is I/O headroom, not a
    scoring parameter."""
    import urllib.request                            # localhost only; outside the cisco_toolkit fence
    body = {"model": model, "stream": False, "keep_alive": "15m", "think": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_predict": 1024},
            "format": judge_schema()}
    req = urllib.request.Request(
        f"http://{OLLAMA_HOST}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (localhost, opt-in)
        obj = json.load(r)
    return str((obj.get("message") or {}).get("content", "") or "")


def _grade_once(model: str, prompt: str, *, retries: int = 1) -> Optional[int]:
    """One prompt → one 0–3 grade, or None on model/parse failure (never a fabricated grade).
    One retry for TRANSIENT failures (HTTP hiccup, connection reset); a deterministic failure
    repeats and still lands on an honest None, which the gate's missing-anchor check fails loudly."""
    for _ in range(1 + max(0, retries)):
        try:
            obj = json.loads(_chat(model, prompt))
            g = obj.get("grade")
            if isinstance(g, (int, float)) and int(g) in (0, 1, 2, 3):
                return int(g)
        except Exception:
            pass
    return None


def grade_pairs(pairs: List[Dict[str, Any]], *, model: str, passes: int) -> Dict[str, Any]:
    grades: List[Dict[str, Any]] = []
    for pair in pairs:
        prompts = judge_prompts(str(pair.get("query", "")), str(pair.get("doc", "")),
                                str(pair.get("excerpt", "")), dict(pair.get("rubric") or {}))
        final_by_pass: List[Optional[int]] = []
        detail: List[Dict[str, Any]] = []
        for p in range(passes):
            n = _grade_once(model, prompts["neutral"])
            a = _grade_once(model, prompts["adversarial"])
            final = combine_dual(n, a) if (n is not None and a is not None) else None
            final_by_pass.append(final)
            detail.append({"pass": p + 1, "neutral": n, "adversarial": a, "final": final})
        grades.append({"pid": str(pair.get("pid")), "final_by_pass": final_by_pass,
                       "detail": detail})
    return {"ok": True, "model": model, "passes": passes, "grades": grades}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    model = DEFAULT_MODEL
    if "--model" in argv:
        model = argv[argv.index("--model") + 1]
    if "--probe" in argv:
        print(json.dumps({"listening": _listening(), "model": model}))
        return 0
    if "--pairs" not in argv:
        print(json.dumps({"ok": False,
                          "reason": "usage: --pairs <payload.json> [--model M] | --probe"}))
        return 0
    if not _listening():
        print(json.dumps({"ok": False, "model": model,
                          "reason": f"Ollama not listening on {OLLAMA_HOST}"}))
        return 0                                     # graceful: caller records signal_absent
    path = argv[argv.index("--pairs") + 1]
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        pairs = list(payload.get("pairs", []))
        passes = max(1, int(payload.get("passes", 1)))
    except (OSError, ValueError) as ex:
        print(json.dumps({"ok": False, "reason": f"bad pairs payload: {ex}"}))
        return 0
    print(json.dumps(grade_pairs(pairs, model=model, passes=passes), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
