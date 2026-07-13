"""Learnings discipline — the feedback nerve's distilled, verifiable, SessionStart-read store.

Phase 0 of ``docs/autonomous-brain-plan-v4-final-2026-07-06.md``: the feedback nerve
"distills → learnings.md (verifiable facts only)". This module is the *discipline* on that store —
a linter that keeps ``docs/quality/learnings.md`` lean, cited, and free of self-assessment, so it can
be injected at session start without rotting into a pep-talk.

The four rules (each a real defect the coasting trap or context bloat would otherwise cause):

1. **Lean** — under 100 lines, so it stays cheap to read at every SessionStart.
2. **Cited** — every learning carries an evidence pointer (a file/test path, a commit, or an explicit
   ``Evidence:`` marker). A claim with no way to check it is not a learning.
3. **Verifiable, never a self-assessment** — no coasting language ("great progress", "on track",
   "nailed it", …). The README names the trap: an agent that records "great progress" reads it back
   and stops trying. Learnings are falsifiable facts about the code/engine, not morale.
4. **Non-redundant** — one claim, one entry. The write discipline is SelfMem's operator vocabulary
   (arXiv 2607.03726, ADR-0003 §3b): ``ADD`` a genuinely new fact; ``REPLACE`` a stale one in place;
   ``MERGE`` a related pair; ``REFINE`` wording without duplicating; ``ARCHIVE`` what no longer holds;
   ``RECORD_EXACT`` a verbatim contract. The through-line is *replace stale, don't accumulate* — so two
   entries making the same claim are an ``ADD`` where ``REPLACE``/``MERGE`` was due, and are flagged.
   (The other operators are writer-intent discipline the store can't read; the linter mechanically
   enforces only the anti-accumulation *symptom* — a duplicated claim.)

Distinct from ``docs/log.md`` (the raw per-session ``/retro`` log — the SOURCE) and from the vault
(career/domain knowledge, promoted via ``/ingest``). This store is the *distilled repo/engine facts*
that should shape every session. Pure stdlib, offline, total on bad input.
"""
from __future__ import annotations

import re
from typing import List

# A learning is cited if it names a repo artifact or an explicit evidence marker. Kept broad enough to
# be non-annoying, strict enough that a bare opinion (no pointer) fails.
_CITATION_RE = re.compile(
    r"""\b\S+\.(?:py|md|json|toml|sh|html|ya?ml)\b   # a file path (cisco_toolkit/eval_harness.py, ...)
        | \btests/\S+                                  # a test path
        | \bcommit\s+[0-9a-f]{7,40}\b                  # a commit sha
        | \b(?:Evidence|Ref|Proof|See)\s*[:=]         # an explicit evidence marker
        | §\s*\d                                       # a section reference
    """, re.I | re.X)

# Self-assessment / coasting language — unfalsifiable morale, the exact thing the store must NOT hold.
_COASTING_RE = re.compile(
    r"\b(?:great|solid|good|excellent|strong|steady|nice)\s+progress"
    r"|\bon\s+track\b|\bnailed\s+it\b|\blooking\s+good\b|\bwell\s+done\b|\bgood\s+job\b"
    r"|\bmaking\s+(?:great|good)\s+(?:progress|headway)|\bproud\s+of\b|\bimpressive\b"
    r"|\bawesome\b|\bfantastic\b|\bcrushed\s+it\b|\bhuge\s+win\b", re.I)

# Lines that are structure, not learnings: headings, blanks, and prose in the header block.
_BULLET_RE = re.compile(r"^-\s+\S")


def parse_learnings(text: str) -> List[str]:
    """The learning entries: each top-level ``- `` bullet plus any indented continuation lines
    (so an ``Evidence:`` on the next indented line counts toward that entry). Header prose and
    headings are ignored — only bullets are learnings."""
    entries: List[str] = []
    cur: List[str] = []
    for line in (text or "").splitlines():
        if _BULLET_RE.match(line):
            if cur:
                entries.append("\n".join(cur))
            cur = [line]
        elif cur and (line.startswith((" ", "\t"))):     # indented continuation of the current entry
            cur.append(line)
        elif cur and line.strip() == "":                 # blank line ends the entry
            entries.append("\n".join(cur))
            cur = []
        # a non-indented non-bullet line (heading/prose) also ends any open entry
        elif cur:
            entries.append("\n".join(cur))
            cur = []
    if cur:
        entries.append("\n".join(cur))
    return entries


def _short(entry: str) -> str:
    first = entry.splitlines()[0] if entry else ""
    first = first.lstrip("- ").strip()
    return (first[:70] + "…") if len(first) > 70 else first


def _claim_key(entry: str) -> str:
    """The normalized first-line CLAIM, for duplicate detection (SelfMem write-vocab, rule 4). Strip the
    bullet, drop backticks, collapse whitespace, lowercase, and shed edge punctuation — so ``- `foo()`
    returns []`` and ``foo() returns [] —`` key identically. Keys on the claim, NOT the evidence line,
    so two distinct facts that cite the same file are not flagged. Empty first line → empty key (skipped)."""
    first = entry.splitlines()[0] if entry else ""
    first = first.lstrip("- ").replace("`", "")
    # drop a TRAILING evidence section ("… Evidence: x", "… — Ref: y") so the same claim with a
    # different pointer keys the same; claim-internal file refs are kept (they ARE the claim)
    first = re.split(r"\s*[—–-]?\s*(?:Evidence|Ref|Proof|See)\s*[:=].*$", first, maxsplit=1, flags=re.I)[0]
    first = re.sub(r"\s+", " ", first).strip().lower()
    return first.strip(".,;:!?—–-…\"'() ")


def lint_learnings(text: str, *, max_lines: int = 100) -> List[str]:
    """Discipline violations for a learnings store, most-structural first. Empty == disciplined.

    Coverage-honest: an EMPTY store (no entries yet) is valid — absence is absence, not a violation.
    The rules fire only on real content: an over-length file, an uncited learning, or a
    self-assessment. Total on bad input (a non-str yields a single 'not text' violation)."""
    if not isinstance(text, str):
        return ["learnings store is not text"]
    violations: List[str] = []
    n_lines = len(text.splitlines())
    if n_lines >= max_lines:
        violations.append(f"too long: {n_lines} lines (must stay under {max_lines}; distill it)")
    seen_claims: dict = {}
    for entry in parse_learnings(text):
        if not _CITATION_RE.search(entry):
            violations.append(f"uncited learning (no evidence pointer): {_short(entry)!r}")
        m = _COASTING_RE.search(entry)
        if m:
            violations.append(f"self-assessment/coasting language {m.group(0)!r} (not a verifiable fact): {_short(entry)!r}")
        key = _claim_key(entry)
        if key and key in seen_claims:
            violations.append(
                f"duplicate learning (same claim as {seen_claims[key]!r} — REPLACE/MERGE stale, don't ADD): {_short(entry)!r}")
        elif key:
            seen_claims[key] = _short(entry)
    return violations


def lint_file(path: str, *, max_lines: int = 100) -> List[str]:
    """Lint a learnings file on disk. A missing file is a violation (the store should exist, even if
    it only holds the header) — but distinct from a discipline breach so the caller can tell them
    apart."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return [f"learnings store not found: {path}"]
    return lint_learnings(text, max_lines=max_lines)


def main(argv=None) -> int:
    """CLI: ``python -m cisco_toolkit.learnings --lint [path]`` — exit 1 (with the violations printed)
    if the store breaks discipline, else 0. Defaults to docs/quality/learnings.md."""
    import os
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    args = [a for a in argv if not a.startswith("-")]
    path = args[0] if args else os.path.join("docs", "quality", "learnings.md")
    violations = lint_file(path)
    if violations:
        print(f"learnings discipline FAILED ({path}):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"learnings discipline OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
