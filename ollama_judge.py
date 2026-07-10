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
``--append-baseline`` additionally records the measurement as a ``judge-baseline`` row on the quality
scorecard (P0-6a: the row :func:`cisco_toolkit.scorecard.latest_judge_baseline` stamps QA verdicts from).
Ollama down → nothing is appended (signal_absent — a measurement row is never fabricated).
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
from typing import Any, Callable, Dict, List, Optional

from cisco_toolkit import defect_panel as P
from cisco_toolkit import scorecard as SCD

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
    """The judge prompt: a NEUTRAL per-condition checklist — check the deliverable against each defect
    definition and REJECT iff one clearly holds, else APPROVE. Measured to *discriminate* (approves clean
    work, catches blatant defects) where a leaning prompt over-rejects ('reject everything') or over-approves
    ('most are fine'). P1-3 rung-1 refinement (same neutral framing, measured 2026-07-10): the deliverable
    comes FIRST, the conditions are NUMBERED, and the reasoning must WALK them — one line per condition,
    quoting the checked line, ending HOLDS or DOES-NOT-HOLD. The prior single-block phrasing let the 4B model
    form one global impression and default to APPROVE (it missed even the literal '(none)' and 253-vs-250
    triggers, TNR 0.2); forcing the walk is what makes it actually execute each check. Output shape enforced
    by :func:`judge_schema`. Rung-2 (measured 2026-07-10): rung 1 raised detection (rejection 0.4) but both
    rejections bound ``defect_class`` to the FIRST enum value — so the reasoning must now END with a literal
    ``HELD: <condition name or NONE>`` line and ``defect_class`` copies it (an explicit copy source right
    before the enum field is generated), and the rollback guard is reworded (rung 1's 'only the literal
    rollback (none) is missing' parsed as \"the string is absent\")."""
    vocab = ", ".join(classes if classes is not None else _text_visible_classes())
    return (
        "You are an independent senior Cisco reviewer doing QA on ONE migration-deliverable excerpt.\n\n"
        "DELIVERABLE:\n"
        f"{deliverable_text}\n\n"
        "Check the DELIVERABLE against each numbered condition below, ONE AT A TIME. In 'reasoning', write\n"
        "one line per condition: its name, the exact deliverable line you checked (quote it), and the word\n"
        "HOLDS or DOES-NOT-HOLD. Do not skip any condition. A condition HOLDS only if its exact trigger is\n"
        "present. Do not reject on vague suspicion: a device simply being 'healthy' is normal, and a\n"
        "rollback stated as a command or as 'n/a - verification step' is a real rollback — condition 1 is\n"
        "about the placeholder '(none)'.\n"
        "1. missing-rollback: a MOP step whose rollback field reads '(none)' — that step has no rollback.\n"
        "2. phantom-health: a device in an 'assessed: healthy' or 'Redundancy ... verified' line whose name\n"
        "   the COVERAGE line lists under NOT collected (only if the healthy/verified device is the\n"
        "   not-collected one).\n"
        "3. unsafe-sequence: an irreversible step (withdraw/remove) whose [order] number is LOWER than the\n"
        "   [order] number of a 'verify' step.\n"
        "4. cross-artifact-mismatch: on the 'Endpoint total' line, the (workbook) number differs from the\n"
        "   (runbook) number.\n"
        "5. empty-nrfu-evidence: an 'NRFU ... PASS' line whose captured output is '(empty)'.\n"
        "The LAST line of 'reasoning' must be exactly 'HELD: <name of the one condition that HOLDS>' —\n"
        "using the condition's name as written above — or 'HELD: NONE' if none holds.\n"
        "Then: verdict = REJECT if a condition HOLDS, else APPROVE; defect_class = exactly the value you\n"
        f"wrote after 'HELD:' (one of: {vocab}; or NONE).\n"
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

    Three headline metrics: ``approves_clean`` (SPECIFICITY — a good deliverable MUST pass; a judge that
    rejects it has none, so its panel rejections are worthless), ``rejection_rate`` (did it catch the bad
    work at all — the veto signal), and ``localized_tnr`` (did it catch AND correctly name the defect). The
    clean control is measured FIRST and on purpose: a high ``rejection_rate`` means nothing unless
    ``approves_clean`` is True (the 'rejects everything' trap this harness must not fall into)."""
    probe = listening if listening is not None else _listening
    if not probe(host):
        return {"ok": False, "reason": f"Ollama not listening on {host} — pull the model and start Ollama"}
    classes = _text_visible_classes()
    schema = judge_schema(classes)
    do_chat = chat if chat is not None else (lambda prompt: _chat(model, prompt, fmt=schema))
    # SPECIFICITY control: judge a known-good deliverable — it must APPROVE. Measured before the panel so a
    # judge that rejects everything is exposed rather than flattering its rejection_rate.
    try:
        clean_raw = do_chat(build_prompt(P.render_text(P.good_deliverable()), classes))
    except Exception as ex:
        clean_raw = f"(judge error: {ex})"
    approves_clean = parse_verdict(clean_raw)["verdict"] == "APPROVE"
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
    return {"ok": True, "model": model, "approves_clean": approves_clean, "verdicts": verdicts, **score}


def baseline_row(res: Dict[str, Any], *, date: str, commit: str) -> Dict[str, Any]:
    """Project a successful :func:`run_baseline` result onto the scorecard schema as the
    ``judge-baseline`` row (P0-6a) — a MEASUREMENT, not a verdict: ``verdict``/``score``/
    ``counterexamples`` stay null and ``judge_tnr`` carries the measured localized TNR. Fail-safe on
    specificity: when the judge rejected the clean control (``approves_clean`` False) its rejections
    are worthless, so ``judge_tnr`` is recorded null (with the raw numbers in ``notes``) — a
    no-specificity judge must never become the TNR that stamps later APPROVEs as gating."""
    tnr = res.get("localized_tnr") if res.get("approves_clean") else None
    per = ",".join(f"{v.get('defect_id')}:{'R' if v.get('verdict') == 'REJECT' else 'A'}"
                   for v in res.get("verdicts", []))
    if not res.get("approves_clean"):
        state = (f"NO SPECIFICITY (rejected the clean control) — measured rejection "
                 f"{res.get('rejection_rate')}/localized {res.get('localized_tnr')} recorded as null trust")
    elif tnr is not None and tnr >= SCD.JUDGE_TNR_FLOOR:
        state = f"clears the {SCD.JUDGE_TNR_FLOOR} floor -> freshly-stamped judge APPROVEs are gating"
    else:
        state = f"below the {SCD.JUDGE_TNR_FLOOR} floor -> judge APPROVEs stay PROVISIONAL/advisory"
    notes = (f"cross-family LLM judge {res.get('model')} re-baseline: localized TNR={res.get('localized_tnr')}, "
             f"rejection_rate={res.get('rejection_rate')}, approves_clean={res.get('approves_clean')} "
             f"over the {res.get('n')}-defect text-visible panel ({per}); {state}")
    return {"date": date, "deliverable": SCD.JUDGE_BASELINE_DELIVERABLE, "score": None,
            "verdict": None, "judge_tnr": tnr, "provisional": None, "counterexamples": None,
            "laws_tripped": [], "commit": commit, "notes": notes}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    record = "--append-baseline" in argv
    if record:
        argv.remove("--append-baseline")
    model = argv[0] if argv else DEFAULT_MODEL
    res = run_baseline(model)
    if not res.get("ok"):
        print(f"[ollama-judge] {res.get('reason')}")
        if record:
            print("[ollama-judge] signal_absent — no baseline row appended (a measurement is never fabricated)")
        return 0                                               # graceful: nothing measured, not an error
    print(f"[ollama-judge] model={res['model']}  panel={res['n']} text-visible defects")
    print(f"  approves clean       = {res['approves_clean']}   (SPECIFICITY: a good deliverable MUST pass)")
    print(f"  rejection rate       = {res['rejection_rate']}   (caught bad work — meaningful ONLY if approves_clean)")
    print(f"  localized TNR        = {res['localized_tnr']}   (rejected WITH the right defect class)")
    print(f"  unlocalized rejects  = {res['unlocalized_rejection_rate']}   (rejected, wrong/'no' class)")
    for v in res["verdicts"]:
        print(f"    {v['defect_id']}: {v['verdict']:<7} class={v['defect_class']}")
    if not res["approves_clean"]:
        print("  ! WARNING: the judge REJECTED a clean deliverable -> no specificity; its rejections are\n"
              "    worthless (it rejects everything). Fix the prompt/model before trusting any rejection rate.")
    print("  (the deterministic arm catches all 12 by construction; this is the LLM judge's floor to clear)")
    if record:
        row = baseline_row(res, date=SCD._today(), commit=SCD._git_commit())
        path = os.environ.get("SCORECARD_FILE") or SCD.SCORECARD_PATH
        if SCD.append_row(row, path):
            print(f"scorecard += judge-baseline judge_tnr={row['judge_tnr']} "
                  f"(floor {SCD.JUDGE_TNR_FLOOR}) -> {path}")
        else:
            print("scorecard: identical baseline already recorded (dedupe no-op)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
