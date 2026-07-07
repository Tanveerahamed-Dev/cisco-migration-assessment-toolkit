"""Quality scorecard — the append-only feedback log + the ``/qa``-verdict appender.

Phase 0 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``. Two jobs:

1. **Parse an independent QA verdict** (the ``deliverable-qa-reviewer`` subagent's output) into one
   scorecard row — the schema in ``docs/quality/README.md`` (date / deliverable / score / verdict /
   counterexamples / laws_tripped / commit / notes).
2. **Append it** to ``docs/quality/scorecard.jsonl``, one JSON object per line, append-only.

What it records is the **independent verifier's verdict** — a *verifiable fact* (proposer ≠ verifier),
never the main agent's self-assessment (the coasting trap the README warns about). ``score`` stays
``null`` on this path: the numeric eval score comes from the golden-snapshot harness
(:mod:`cisco_toolkit.eval_harness`), not from a QA transcript.

**Coverage-honest & conservative:** if the text is not confidently a QA verdict, :func:`parse_qa_verdict`
returns ``None`` and nothing is appended — a missing verdict is recorded as *nothing*, never a
fabricated "APPROVE". The hook that drives this (``.claude/hooks/scorecard-append.sh``) is fail-open:
any error appends nothing and never blocks the turn.

Pure-stdlib. The parser does no I/O; :func:`run_hook` does the file/git side (so the parser is unit
testable without a transcript or a repo).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

# Path is relative to the repo root; callers resolve it (the hook cd's to the toplevel first).
SCORECARD_PATH = os.path.join("docs", "quality", "scorecard.jsonl")

# The append-only row schema (docs/quality/README.md). Emitted in this order.
SCHEMA_KEYS = ("date", "deliverable", "score", "verdict", "counterexamples",
               "laws_tripped", "commit", "notes")

# Deliverable family tokens -> the canonical `deliverable` label the scorecard uses.
_FAMILY = [
    (r"\bhld\b", "hld"), (r"\blld\b", "lld"), (r"\bmop\b", "mop"), (r"\bcrd\b", "crd"),
    (r"\brunbook\b", "runbook"), (r"\barchreview\b|\barchitecture review\b", "archreview"),
    (r"\bengagement\b", "engagement"), (r"\bops handbook\b|\bops\b", "ops"),
    (r"\bdeck\b|\bslides?\b", "deck"), (r"\bworkbook\b|\bexcel\b", "workbook"),
    (r"\bexplorer\b", "explorer"), (r"\bdesign\b", "design"), (r"\bsnapshot\b", "snapshot"),
]

# The structural signature of a real deliverable-qa-reviewer verdict: a per-artifact verdict LINE —
# "design.docx — BLOCK", "runbook.docx: APPROVE", "MOP - BLOCK". REQUIRING this is what distinguishes
# an actual reviewer verdict from MAIN-AGENT PROSE that merely *discusses* QA: prose mentions
# "verdict"/"BLOCK" and may even render markdown tables, but it has no "<artifact> <sep> VERDICT" line,
# so a session summary no longer fabricates a scorecard row. Deliberately strict — favour a MISSED
# verdict (no row; the verdict is still in the transcript) over a fabricated one.
_ARTIFACT_VERDICT_RE = re.compile(
    r"(?im)^[\s>*_.\-]{0,8}([A-Za-z][\w./+-]{1,40})[ \t]*(?:[—–:]|-)[ \t]*(APPROVE|APPROVED|BLOCK|BLOCKED)\b")
# Any verdict token — used only to pick a factual notes line when a verdict carries no finding table.
_VERDICT_RE = re.compile(r"\b(APPROVE|APPROVED|BLOCK|BLOCKED)\b")
_LAW_RE = re.compile(r"\bL(\d{1,2})\b|\bLaw\s+(\d{1,2})\b")


def _families_in(hay: str) -> List[str]:
    out: List[str] = []
    for pat, label in _FAMILY:
        if re.search(pat, hay, re.I) and label not in out:
            out.append(label)
    return out


def _infer_deliverable(text: str) -> str:
    """The single deliverable label, or 'set' when a QA pass spans several (or names none).

    Strongest signal first: the artifact FILES the verdict names ("runbook.docx", "design.docx") —
    a bare word like "the snapshot" in prose is a source-of-truth reference, not the reviewed
    artifact, so filenames win. Falls back to bare family tokens only when no file is named."""
    named = re.findall(r"\b([A-Za-z_]+)\.(?:docx|pptx|xlsx|html)\b", text, re.I)
    fams = []
    for stem in named:
        fams += [f for f in _families_in(stem) if f not in fams]
    if not fams:
        fams = _families_in(text)
    return fams[0] if len(fams) == 1 else "set"


def _finding_rows(text: str) -> List[str]:
    """The pipe-delimited finding rows (location | claimed | source-of-truth | severity), excluding
    the header and separator rows. The QA agent's documented finding shape."""
    rows = []
    for line in text.splitlines():
        if line.count(" | ") >= 2 and "---" not in line:
            low = line.lower()
            if not ("severity" in low and ("claimed" in low or "location" in low)):  # skip header row
                rows.append(line.strip().strip("|").strip())
    return rows


def _laws_tripped(text: str) -> List[str]:
    ids = set()
    for m in _LAW_RE.finditer(text):
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= 10:                       # the Standard has ten Laws; ignore stray "L47" tokens
            ids.add(n)
    return [f"L{n}" for n in sorted(ids)]


def parse_qa_verdict(text: str, *, date: str, commit: str) -> Optional[Dict[str, Any]]:
    """Turn a QA verdict message into one scorecard row, or ``None`` if ``text`` is not confidently a
    QA verdict (conservative: no confident verdict → no row, never a fabricated one).

    Requires the reviewer's structural signature — at least one per-artifact verdict LINE
    ("design.docx — BLOCK"). Text that merely *discusses* QA (a session summary, another subagent)
    has none and yields ``None`` (no fabricated row). ``verdict`` is BLOCK if any artifact blocked (a
    single blocking finding blocks the set), else APPROVE. ``counterexamples`` is the number of
    grounded findings (the pipe-delimited rows; falling back to 1 for a BLOCK with no enumerated
    table). ``score`` is ``None`` — the numeric eval score is the golden harness's job, not a transcript's.
    """
    if not text or not text.strip():
        return None
    artifact_verdicts = _ARTIFACT_VERDICT_RE.findall(text)
    if not artifact_verdicts:
        return None                            # no per-artifact verdict line -> not a verdict, record nothing
    verdicts = {v.upper() for _artifact, v in artifact_verdicts}
    blocked = bool(verdicts & {"BLOCK", "BLOCKED"})
    findings = _finding_rows(text)
    if blocked:
        counterexamples = len(findings) if findings else 1
    else:
        counterexamples = len(findings)        # an APPROVE may still carry advisory findings
    notes = findings[0] if findings else _first_rationale(text, blocked)
    return {
        "date": date,
        "deliverable": _infer_deliverable(text),
        "score": None,                         # QA-verdict path: numeric score is the harness's job
        "verdict": "BLOCK" if blocked else "APPROVE",
        "counterexamples": counterexamples,
        "laws_tripped": _laws_tripped(text),
        "commit": commit,
        "notes": _truncate(notes, 220),
    }


def _first_rationale(text: str, blocked: bool) -> str:
    """A short factual note when there is no finding table: the first line mentioning the verdict."""
    for line in text.splitlines():
        s = line.strip()
        if s and _VERDICT_RE.search(s):
            return s
    return "QA verdict recorded (no enumerated findings)" if not blocked else "QA blocked (no enumerated findings)"


def _truncate(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --- persistence -------------------------------------------------------------------------------

def read_rows(path: str = SCORECARD_PATH) -> List[Dict[str, Any]]:
    """Every well-formed row, in file order. Missing/empty file -> [] (coverage-honest: absence is
    absence). Malformed lines are skipped, not fatal."""
    try:
        with open(path, encoding="utf-8") as f:
            out = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
            return out
    except OSError:
        return []


def _same_verdict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = ("deliverable", "verdict", "counterexamples", "commit", "notes")
    return all(a.get(k) == b.get(k) for k in keys)


def append_row(row: Dict[str, Any], path: str = SCORECARD_PATH, *, dedupe: bool = True) -> bool:
    """Append one row (JSON, one line). Returns True if written. With ``dedupe`` (default), a row
    identical to the last one already logged is skipped — so a double-fired hook (SubagentStop then
    SessionEnd for the same QA run) can't write the same verdict twice. Creates the file/dir if
    absent."""
    if not isinstance(row, dict):
        return False
    if dedupe:
        existing = read_rows(path)
        if existing and _same_verdict(existing[-1], row):
            return False
    ordered = {k: row.get(k) for k in SCHEMA_KEYS}
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=True) + "\n")
    return True


# --- transcript extraction + hook glue ---------------------------------------------------------

def _iter_assistant_texts(transcript_path: str) -> List[str]:
    """Assistant message texts from a Claude Code JSONL transcript, oldest→newest. Defensive across
    schema shapes; total (never raises) — an unreadable/other-shape transcript yields []."""
    texts: List[str] = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return texts
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        role = obj.get("role") or (obj.get("message") or {}).get("role") or obj.get("type")
        if role != "assistant":
            continue
        content = obj.get("content")
        if content is None:
            content = (obj.get("message") or {}).get("content")
        text = _content_to_text(content) or (obj.get("text") if isinstance(obj.get("text"), str) else "")
        if text and text.strip():
            texts.append(text)
    return texts


def _content_to_text(content: Any) -> str:
    """Flatten an assistant `content` (string, or list of {type:text,text:...} blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return ""


def extract_last_assistant_text(transcript_path: str) -> str:
    """The final assistant message's text ("" if none) — the subagent's verdict at SubagentStop."""
    texts = _iter_assistant_texts(transcript_path)
    return texts[-1] if texts else ""


def _git_commit() -> str:
    """Short HEAD SHA, or '' if git is unavailable (fail-open — a row without a SHA beats no row)."""
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _today() -> str:
    try:
        import datetime
        return datetime.date.today().isoformat()
    except Exception:
        return ""


def run_hook(stdin_text: str, *, path: str = SCORECARD_PATH,
             date: Optional[str] = None, commit: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """SubagentStop/SessionEnd glue: read the hook payload, find the most recent QA verdict in the
    referenced transcript, and append it. Returns the appended row, or ``None`` when there is no QA
    verdict to record (or it was a dedupe no-op). Total — never raises (fail-open)."""
    try:
        payload = json.loads(stdin_text) if stdin_text and stdin_text.strip() else {}
    except Exception:
        payload = {}
    transcript = payload.get("transcript_path") if isinstance(payload, dict) else None
    date = date or _today()
    commit = commit if commit is not None else _git_commit()
    candidates: List[str] = []
    if transcript:
        candidates = list(reversed(_iter_assistant_texts(transcript)))[:6]  # newest-first, bounded
    for text in candidates:
        row = parse_qa_verdict(text, date=date, commit=commit)
        if row:
            return row if append_row(row, path) else None
    return None


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. ``--hook`` reads a hook payload on stdin and appends a QA verdict if present; ``--show``
    prints the tail of the scorecard. Always exits 0 on the hook path (fail-open)."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    # The hook uses the default path (zero-arg). SCORECARD_FILE lets a dry-run/test redirect it.
    path = os.environ.get("SCORECARD_FILE") or SCORECARD_PATH
    if "--show" in argv:
        rows = read_rows(path)
        if not rows:
            print("scorecard: no entries yet")
        else:
            for r in rows[-10:]:
                print(json.dumps(r, ensure_ascii=True))
        return 0
    if "--hook" in argv:
        try:
            row = run_hook(sys.stdin.read(), path=path)
            if row:
                print(f"scorecard += {row['deliverable']} {row['verdict']} "
                      f"(counterexamples={row['counterexamples']}, laws={row['laws_tripped']})")
        except Exception:
            pass
        return 0
    print(__doc__.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
