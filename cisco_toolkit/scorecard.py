"""Quality scorecard — the append-only feedback log + the ``/qa``-verdict appender.

Phase 0 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``. Two jobs:

1. **Parse an independent QA verdict** (the ``deliverable-qa-reviewer`` subagent's output) into one
   scorecard row — the schema in ``docs/quality/README.md`` (date / deliverable / score / verdict /
   judge_tnr / provisional / counterexamples / laws_tripped / commit / notes).
2. **Append it** to ``docs/quality/scorecard.jsonl``, one JSON object per line, append-only.

What it records is the **independent verifier's verdict** — a *verifiable fact* (proposer ≠ verifier),
never the main agent's self-assessment (the coasting trap the README warns about). ``score`` stays
``null`` on this path: the numeric eval score comes from the golden-snapshot harness
(:mod:`cisco_toolkit.eval_harness`), not from a QA transcript.

**Proposer ≠ verifier is mechanical here (P0-2 / gap G-002):** rows carry an optional provenance pair
(``authored_by`` / ``reviewed_by``) and :func:`check_independence` REFUSES any record whose two
identities are the same non-empty string — a self-review can never mint a quality row (the record
arms refuse loudly with the reason; :func:`append_row` backstops the same rule at the persistence
layer). Honest residual: the check is over *declared* identity strings, which an agent could
misdeclare — it raises the bar, it is not proof of independence; the hard boundary stays the
OS/permission layer (CLAUDE.md trust-boundary note).

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
# `judge_tnr` = the measured true-negative rate of the JUDGE that produced this verdict
# (:mod:`cisco_toolkit.defect_panel` seeds the panel; ``ollama_judge`` measures), or ``null`` when
# unmeasured. A QA verdict is a Claude judge on Claude's work, so an APPROVE is only trustworthy to the
# extent the judge is *shown* to REJECT known-bad work (Jain et al. 2510.11822: LLM judges default to
# TNR < 25%). ``null`` = trust unquantified — never a fabricated confidence. A deterministic
# ``eval_harness`` row is bias-free and simply carries ``null`` here.
# `provisional` (P0-6 / DEC-004) makes that trust judgement MACHINE-READABLE: ``true`` on any APPROVE
# whose ``judge_tnr`` is null or below :data:`JUDGE_TNR_FLOOR` — that verdict is ADVISORY and nothing
# may gate on it (:func:`is_provisional` is the one predicate; enforced at :func:`append_row`).
# `authored_by` / `reviewed_by` (P0-2 / G-002) = the optional provenance pair — which agent authored
# the reviewed deliverable(s) and which produced this verdict. Absent -> honest ``null`` (provenance
# undeclared), and pre-P0-2 rows on disk carry no such keys at all — both stay valid (back-compat).
# :func:`check_independence` is the mechanical proposer≠verifier wedge over the pair.
SCHEMA_KEYS = ("date", "deliverable", "score", "verdict", "judge_tnr", "provisional",
               "counterexamples", "laws_tripped", "commit", "notes", "authored_by", "reviewed_by")

# The broken-instrument threshold: below this measured TNR an LLM judge approves almost anything
# (Jain et al. 2510.11822 — LLM judges default to TNR < 25%), so its APPROVE quantifies nothing. This
# constant OWNS the 0.25 figure — docs/quality/README.md cites it; never restate it elsewhere (SSOT Law 1).
JUDGE_TNR_FLOOR = 0.25
# The `deliverable` label of a judge-baseline measurement row (written by `ollama_judge --append-baseline`;
# read back by :func:`latest_judge_baseline` to stamp each subsequent QA verdict).
JUDGE_BASELINE_DELIVERABLE = "judge-baseline"

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


# --- proposer != verifier wedge (P0-2 / gap G-002) ----------------------------------------------

def check_independence(authored_by: Optional[str], reviewed_by: Optional[str]) -> Optional[str]:
    """The refusal reason when ``authored_by`` and ``reviewed_by`` name the SAME non-empty identity,
    else ``None`` (the record proceeds). Case- and whitespace-insensitive ("Design-Author " ==
    "design-author" — a cosmetic respelling is not independence).

    Absent/empty identities do NOT refuse: the pair is optional (pre-P0-2 rows and callers carry no
    provenance), so the wedge trips only on a POSITIVE self-review signal, never on missing metadata
    — conservative, like every other guard in this module. Honest residual: this checks *declared*
    identity strings, which an agent could misdeclare; the wedge raises the bar (an honest caller can
    no longer record a self-review), it is not proof — the hard boundary is the OS/permission layer.
    """
    a = (authored_by or "").strip()
    r = (reviewed_by or "").strip()
    if a and r and a.casefold() == r.casefold():
        return (f"refused: authored_by == reviewed_by ({a!r}) -- proposer != verifier (P0-2/G-002): "
                f"a self-review cannot mint a scorecard row; nothing recorded. Have an independent "
                f"agent (e.g. deliverable-qa-reviewer) produce the verdict, or omit the identity flags.")
    return None


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


# --- judge trust: PROVISIONAL vs quantified verdicts (P0-6 / DEC-004; gap G-006) -----------------

def _num(v: Any) -> Optional[float]:
    """``v`` as a float when it is a real number (bools excluded — True is an int), else ``None``."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def latest_judge_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The most recent judge-baseline row carrying a MEASURED (numeric) ``judge_tnr``, or ``None``.
    File order is append order, so the last match is the current baseline. A baseline row without a
    numeric measurement is skipped — it quantifies nothing and must stamp nothing."""
    for r in reversed(rows or []):
        if (isinstance(r, dict) and r.get("deliverable") == JUDGE_BASELINE_DELIVERABLE
                and _num(r.get("judge_tnr")) is not None):
            return r
    return None


def is_provisional(row: Dict[str, Any]) -> bool:
    """THE provisional predicate (P0-6 / DEC-004): does this row's APPROVE quantify trust, or merely
    assert it? ``True`` iff the row is a JUDGE verdict — an APPROVE with no numeric ``score`` (a
    numeric score means the deterministic golden harness produced it: bias-free, no judge involved) —
    whose ``judge_tnr`` is unmeasured (null) or measured below :data:`JUDGE_TNR_FLOOR`. A provisional
    APPROVE is ADVISORY: no gate may advance on it. BLOCK rows are never provisional — a grounded
    counterexample stands regardless of the judge's TNR (a weak judge OVER-approves; its rejections
    are findings to verify, not confidence to discount)."""
    if not isinstance(row, dict):
        return False
    if str(row.get("verdict") or "").strip().upper() not in ("APPROVE", "APPROVED"):
        return False
    if _num(row.get("score")) is not None:       # deterministic harness row — bias-free by construction
        return False
    tnr = _num(row.get("judge_tnr"))
    return tnr is None or tnr < JUDGE_TNR_FLOOR


def stamp_judge_trust(row: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """EMIT (P0-6a): annotate a freshly-parsed QA-verdict row with the judge-trust facts before it is
    appended — ``judge_tnr`` from the latest judge-baseline in ``rows`` (``None`` when no baseline was
    ever measured: honest absence, never a guess) plus the machine-readable ``provisional`` mark, so
    PROVISIONAL vs quantified is readable off the row itself. Pure over the given rows; the writers
    (:func:`run_hook` and the ``--record`` arm) pass ``read_rows(path)``. QA-verdict rows only — a
    deterministic ``eval_harness`` row carries no judge and must never inherit a judge's TNR."""
    base = latest_judge_baseline(rows)
    row["judge_tnr"] = _num(base.get("judge_tnr")) if base else None
    row["provisional"] = is_provisional(row)
    return row


def _same_verdict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = ("deliverable", "verdict", "counterexamples", "commit", "notes")
    return all(a.get(k) == b.get(k) for k in keys)


def append_row(row: Dict[str, Any], path: str = SCORECARD_PATH, *, dedupe: bool = True) -> bool:
    """Append one row (JSON, one line). Returns True if written. With ``dedupe`` (default), a row
    identical to the last one already logged is skipped — so a double-fired hook (SubagentStop then
    SessionEnd for the same QA run) can't write the same verdict twice. Creates the file/dir if
    absent. Refuses a self-review row (``authored_by`` == ``reviewed_by``, non-empty) — the
    persistence-layer backstop of the P0-2 wedge; the CLI arms refuse earlier and print why."""
    if not isinstance(row, dict):
        return False
    if check_independence(row.get("authored_by"), row.get("reviewed_by")):
        return False                           # self-review can never mint a row, whatever the caller
    if dedupe:
        existing = read_rows(path)
        if existing and _same_verdict(existing[-1], row):
            return False
    ordered = {k: row.get(k) for k in SCHEMA_KEYS}
    # ENFORCE (P0-6b): the PROVISIONAL mark cannot be dropped or persisted False at the choke point —
    # an APPROVE whose judge_tnr is null / below JUDGE_TNR_FLOOR is written ``provisional: true`` no
    # matter what the caller set. Fabricated confidence is the one direction the schema makes
    # impossible; the conservative direction (a caller forcing True) is left alone.
    if is_provisional(ordered):
        ordered["provisional"] = True
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ordered, ensure_ascii=True) + "\n")
    return True


# --- trend renderer (Phase 1 — "the line you watch go up") -------------------------------------
#
# The scorecard is the record; the *trend* is the signal. This renders the append-only log as a
# time series so a human (or the morning briefing) can watch the two load-bearing lines move:
# counterexamples/cycle DOWN and eval-score UP. Pure derivation over rows -> no I/O; the CLI verb
# and the briefing pass in ``read_rows()``. Coverage-honest throughout: an empty log renders
# "no entries yet" (never a fabricated healthy line), a score series with no scored rows says so
# (absence is absence, not score=0), and a span under two weeks is labelled as not-yet-meaningful
# rather than presented as a trend (Phase-1 acceptance: >= 2 weeks of rows render a trend).

_SPARK = "▁▂▃▄▅▆▇█"   # ▁▂▃▄▅▆▇█ — 8-level block ramp


def _iso_week(date_str: str) -> str:
    """'2026-W27' for a 'YYYY-MM-DD' date; '' if unparseable (malformed rows bucket to ''-> dropped)."""
    try:
        import datetime
        y, m, d = (int(x) for x in str(date_str).split("-")[:3])
        iso = datetime.date(y, m, d).isocalendar()
        return f"{iso[0]}-W{int(iso[1]):02d}"
    except Exception:
        return ""


def _span_days(dates: List[str]) -> Optional[int]:
    """Inclusive day-span between the earliest and latest parseable date, or None if < 1 parseable."""
    import datetime
    ds = []
    for s in dates:
        try:
            y, m, d = (int(x) for x in str(s).split("-")[:3])
            ds.append(datetime.date(y, m, d))
        except Exception:
            pass
    return (max(ds) - min(ds)).days if ds else None


def _sparkline(values: List[Optional[float]]) -> str:
    """A unicode block sparkline over the non-None values (None -> a gap ' '). Flat-safe: a
    single distinct value renders mid-ramp, not a divide-by-zero."""
    present = [v for v in values if isinstance(v, (int, float))]
    if not present:
        return ""
    lo, hi = min(present), max(present)
    rng = hi - lo
    out = []
    for v in values:
        if not isinstance(v, (int, float)):
            out.append(" ")
        elif rng == 0:
            out.append(_SPARK[len(_SPARK) // 2])
        else:
            out.append(_SPARK[min(len(_SPARK) - 1, int((v - lo) / rng * (len(_SPARK) - 1) + 0.5))])
    return "".join(out)


def _direction(series: List[Optional[float]], *, down_is_good: bool) -> str:
    """Trend of the first vs last *present* value. 'improving'/'regressing'/'flat'/'n/a'. For
    counterexamples down_is_good=True (fewer defects = better); for score down_is_good=False."""
    present = [v for v in series if isinstance(v, (int, float))]
    if len(present) < 2:
        return "n/a"
    first, last = present[0], present[-1]
    if first == last:
        return "flat"
    improved = (last < first) if down_is_good else (last > first)
    return "improving" if improved else "regressing"


def summarize_trend(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Structured aggregate of the scorecard for the trend renderer + briefing. Pure; no I/O.

    Buckets rows by ISO week (chronological) and reports, per bucket: cycles, block-rate, mean
    counterexamples, mean eval-score. Plus top-level totals, the two watch-series (counterexamples,
    score) with their direction, the all-time laws-tripped frequency, and the honest coverage flags
    (span, whether it clears the two-week bar, how many rows carried a numeric score)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    n = len(rows)
    dates = [r.get("date") for r in rows if r.get("date")]
    span = _span_days(dates)
    scored_rows = sum(1 for r in rows if isinstance(r.get("score"), (int, float)))

    # Bucket by ISO week, preserving chronological order of first appearance.
    order: List[str] = []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        wk = _iso_week(r.get("date", ""))
        if not wk:
            continue
        if wk not in buckets:
            buckets[wk] = []
            order.append(wk)
    for r in rows:
        wk = _iso_week(r.get("date", ""))
        if wk:
            buckets[wk].append(r)
    order.sort()   # ISO week strings sort chronologically

    def _mean(vals: List[float]) -> Optional[float]:
        return round(sum(vals) / len(vals), 2) if vals else None

    bucket_stats: List[Dict[str, Any]] = []
    for wk in order:
        brs = buckets[wk]
        verdicts = [str(r.get("verdict", "")).upper() for r in brs]
        blocks = sum(1 for v in verdicts if v.startswith("BLOCK"))
        decided = sum(1 for v in verdicts if v.startswith("BLOCK") or v.startswith("APPROVE"))
        cx = [float(r["counterexamples"]) for r in brs if isinstance(r.get("counterexamples"), (int, float))]
        sc = [float(r["score"]) for r in brs if isinstance(r.get("score"), (int, float))]
        bucket_stats.append({
            "bucket": wk, "cycles": len(brs), "blocks": blocks,
            "block_rate": round(blocks / decided, 2) if decided else None,
            "mean_cx": _mean(cx), "mean_score": _mean(sc)})

    cx_series = [b["mean_cx"] for b in bucket_stats]
    score_series = [b["mean_score"] for b in bucket_stats]

    laws: Dict[str, int] = {}
    for r in rows:
        for law in (r.get("laws_tripped") or []):
            laws[law] = laws.get(law, 0) + 1

    return {
        "n": n, "span_days": span, "weeks": len(order), "scored_rows": scored_rows,
        "two_week_bar": bool(span is not None and span >= 14),
        "buckets": bucket_stats,
        "counterexamples": {"series": cx_series, "direction": _direction(cx_series, down_is_good=True)},
        "score": {"series": score_series, "direction": _direction(score_series, down_is_good=False)},
        "laws": dict(sorted(laws.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def render_trend(rows: List[Dict[str, Any]]) -> str:
    """The human-readable quality trend. Empty -> a plain honest line, never a fabricated trend."""
    s = summarize_trend(rows)
    if s["n"] == 0:
        return ("Quality trend — no entries yet. The scorecard records automatically once a /qa "
                "verdict is produced (the SubagentStop appender) or a release eval scores a "
                "deliverable. Absence is absence, not health.")
    span = s["span_days"]
    span_txt = f"{span}d" if span is not None else "?"
    hdr_dates = ""
    dates = sorted(str(r.get("date")) for r in rows if r.get("date"))
    if dates:
        hdr_dates = f" ({dates[0]} → {dates[-1]})"
    L = [f"Quality trend — {s['n']} cycle(s) over {s['weeks']} week(s), span {span_txt}{hdr_dates}"]
    # Per-week table.
    L.append(f"  {'week':<10} {'cycles':>6} {'block%':>7} {'cx/avg':>7} {'score/avg':>9}")
    for b in s["buckets"]:
        br = f"{round(b['block_rate'] * 100)}%" if b["block_rate"] is not None else "  —"
        cx = f"{b['mean_cx']:.2f}" if b["mean_cx"] is not None else "  —"
        sco = f"{b['mean_score']:.0f}" if b["mean_score"] is not None else "  —"
        L.append(f"  {b['bucket']:<10} {b['cycles']:>6} {br:>7} {cx:>7} {sco:>9}")
    # The two watch-lines.
    cx_spark = _sparkline(s["counterexamples"]["series"])
    L.append(f"  counterexamples/cycle  {cx_spark}  {_arrow(s['counterexamples']['direction'], down_is_good=True)}")
    if s["scored_rows"]:
        sc_spark = _sparkline(s["score"]["series"])
        L.append(f"  eval score             {sc_spark}  {_arrow(s['score']['direction'], down_is_good=False)}"
                 f"  ({s['scored_rows']} scored row(s))")
    else:
        L.append("  eval score             — no scored rows yet (scores come from the golden-snapshot "
                 "harness on release; /qa rows carry a verdict, not a number)")
    if s["laws"]:
        L.append("  laws tripped (all-time): " + ", ".join(f"{k}×{v}" for k, v in s["laws"].items()))
    # Coverage-honesty on the span.
    if s["two_week_bar"]:
        L.append("  span ≥ 2 weeks — trend is meaningful.")
    else:
        L.append("  span < 2 weeks — a trend needs ≥ 2 weeks of rows to be meaningful; "
                 "showing what's recorded so far.")
    return "\n".join(L)


def _arrow(direction: str, *, down_is_good: bool) -> str:
    """A terse 'direction + judgement' tag for a watch-line."""
    if direction == "n/a":
        return "(one bucket — no direction yet)"
    if direction == "flat":
        return "→ flat"
    good = (direction == "improving")
    glyph = "↓" if down_is_good else "↑"       # ↓ for cx-good, ↑ for score-good
    return f"{glyph} {direction}" if good else f"{'↑' if down_is_good else '↓'} {direction}"


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
             date: Optional[str] = None, commit: Optional[str] = None,
             authored_by: Optional[str] = None,
             reviewed_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """SubagentStop/SessionEnd glue: read the hook payload, find the most recent QA verdict in the
    referenced transcript, and append it. Returns the appended row, or ``None`` when there is no QA
    verdict to record (or it was a dedupe no-op). Total — never raises (fail-open).

    ``authored_by`` / ``reviewed_by`` annotate the row's provenance pair when the caller knows the
    identities (the ``--record-from`` arm passes them; the hook payload carries none). A self-review
    pair is refused by :func:`append_row` (returns ``None`` — nothing recorded); the CLI refuses
    earlier with the printed reason."""
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
            _annotate_provenance(row, authored_by, reviewed_by)
            stamp_judge_trust(row, read_rows(path))    # EMIT: judge_tnr from the latest baseline (P0-6a)
            return row if append_row(row, path) else None
    return None


def _annotate_provenance(row: Dict[str, Any], authored_by: Optional[str],
                         reviewed_by: Optional[str]) -> None:
    """Set the provenance pair on a parsed row (in place), empty/absent -> key left unset (emitted
    as an honest ``null`` by :func:`append_row`, never a fabricated identity)."""
    if authored_by and authored_by.strip():
        row["authored_by"] = authored_by.strip()
    if reviewed_by and reviewed_by.strip():
        row["reviewed_by"] = reviewed_by.strip()


def _flag_value(argv: List[str], flag: str) -> Optional[str]:
    """The value following ``flag`` in argv, '' if the flag is last (present, valueless), None if
    absent. The module's minimalist arg convention (same as the record arms' path handling)."""
    if flag not in argv:
        return None
    i = argv.index(flag)
    return argv[i + 1] if i + 1 < len(argv) else ""


def _row_line(row: Dict[str, Any]) -> str:
    """The one-line 'what was recorded' echo (the /qa close-the-loop step prints this as evidence).
    Includes the provenance pair when declared, so the transcript shows the wedge saw it."""
    line = (f"scorecard += {row['deliverable']} {row['verdict']} "
            f"(counterexamples={row['counterexamples']}, laws={row['laws_tripped']})")
    if row.get("authored_by") or row.get("reviewed_by"):
        line += f" [authored_by={row.get('authored_by')} reviewed_by={row.get('reviewed_by')}]"
    return line


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. ``trend`` renders the quality trend (the line you watch); ``--hook`` reads a hook payload
    on stdin and appends a QA verdict if present; ``--record-from <transcript>`` / ``--record
    <message-file>`` append the independent reviewer's verdict explicitly (transcript arm / message
    arm) — both accept ``--authored-by <agent>`` / ``--reviewed-by <agent>`` and REFUSE (exit 2,
    reason printed, nothing appended) when the two match non-empty: the P0-2 proposer≠verifier
    wedge — a self-review can never mint a quality row. ``--show`` prints the tail of the scorecard.
    Always exits 0 on the hook path (fail-open — the refusal is a guard tripping by design, not an
    error, and it never occurs on the identity-less hook path)."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 console -> never crash on the sparkline
    except Exception:
        pass
    # The hook uses the default path (zero-arg). SCORECARD_FILE lets a dry-run/test redirect it.
    path = os.environ.get("SCORECARD_FILE") or SCORECARD_PATH
    if "trend" in argv or "--trend" in argv:
        print(render_trend(read_rows(path)))
        return 0
    # The provenance pair for the explicit record arms (P0-2/G-002). Checked BEFORE any parsing so a
    # self-review is refused up front with the reason — exit 2, nothing appended. Optional: absent
    # identities never block an otherwise-valid verdict (they record as null — back-compat).
    authored_by = _flag_value(argv, "--authored-by")
    reviewed_by = _flag_value(argv, "--reviewed-by")
    if "--record-from" in argv or "--record" in argv:
        refusal = check_independence(authored_by, reviewed_by)
        if refusal:
            print(refusal)
            return 2
    if "--record-from" in argv:
        # Record the INDEPENDENT subagent's verdict from ITS transcript — the same source and parser as
        # the SubagentStop hook, but invoked explicitly. For environments where that hook does not fire
        # (Agent-tool subagents under the Claude Agent SDK). The invariant holds: it parses the subagent
        # transcript (never main-agent prose — parse_qa_verdict requires the per-artifact reviewer
        # signature), so only a real independent verdict is recorded.
        i = argv.index("--record-from")
        tpath = argv[i + 1] if i + 1 < len(argv) else ""
        row = run_hook(json.dumps({"transcript_path": tpath}), path=path,
                       authored_by=authored_by, reviewed_by=reviewed_by) if tpath else None
        print(_row_line(row) if row else "no QA verdict found in transcript — nothing recorded")
        return 0
    if "--record" in argv:
        # The MESSAGE arm: record the independent reviewer's verdict from a saved VERBATIM copy of its
        # final message. For harnesses where SubagentStop never fires AND the Agent-tool subagent
        # transcript is never written (the Claude Agent SDK / desktop app) — there the transcript arm
        # above has nothing to read, and without this arm the nerve depends on operator memory. A FILE,
        # not stdin: a cp1252 Windows console mangles em-dashes mid-verdict. Same conservative parser
        # as every arm — text without the per-artifact reviewer signature records NOTHING, so
        # main-agent prose still cannot fabricate a row. Fail-open: unreadable file → nothing appended.
        i = argv.index("--record")
        fpath = argv[i + 1] if i + 1 < len(argv) else ""
        row = None
        try:
            with open(fpath, encoding="utf-8") as f:
                row = parse_qa_verdict(f.read(), date=_today(), commit=_git_commit())
        except Exception:
            row = None
        if row is not None:
            _annotate_provenance(row, authored_by, reviewed_by)
            stamp_judge_trust(row, read_rows(path))    # EMIT: judge_tnr from the latest baseline (P0-6a)
        if row is not None and not append_row(row, path):
            row = None                             # dedupe no-op — already recorded
        print(_row_line(row) if row else "no QA verdict in message file — nothing recorded")
        return 0
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
                print(_row_line(row))
        except Exception:
            pass
        return 0
    print(__doc__.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
