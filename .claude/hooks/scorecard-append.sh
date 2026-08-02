#!/usr/bin/env bash
# SubagentStop hook — append a /qa (deliverable-qa-reviewer) VERDICT as one row to
# docs/quality/scorecard.jsonl. Phase 0 of docs/autonomous-brain-plan-v4-final-2026-07-06.md:
# turns the INDEPENDENT verifier's verdict (proposer != verifier) into a persisted, verifiable
# fact so "improvement" becomes a number the morning briefing can trend — NOT a self-assessment.
#
# Fires on EVERY subagent stop, but appends ONLY when the subagent's final message parses as a QA
# verdict (cisco_toolkit.scorecard discriminates: a verdict token + a QA marker). A design-author
# or any other subagent stop is a no-op. Coverage-honest: if it cannot confidently read a verdict,
# it appends NOTHING (never a fabricated "APPROVE") — an empty scorecard keeps saying "no entries".
#
# Fail-open like verify-green/graph-refresh: any error appends nothing and NEVER blocks the turn
# (always exit 0). Read-only w.r.t. everything except the append-only scorecard; no egress, no
# device access. Disable via /hooks if needed.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0

# Resolve an interpreter that RUNS. `command -v python` succeeds for the Microsoft Store
# App-Execution-Alias stub, which exits 9009 — here that surfaced as this hook warning "exited 49,
# the QA scorecard is NOT being recorded" on every healthy stop: a real message about an unreal
# fault. Fail-open behaviour is unchanged; it is just no longer reached while a working interpreter
# exists.
PY=""
for _c in python python3; do _p=$(command -v "$_c" 2>/dev/null) || continue
  if "$_p" -c "import sys" >/dev/null 2>&1; then PY="$_p"; break; fi; done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
  for _v in -3.12 -3; do _p=$(py "$_v" -c "import sys; print(sys.executable)" 2>/dev/null) || continue
    if [ -n "$_p" ] && [ -x "$_p" ]; then PY="$_p"; break; fi; done; fi
[ -z "$PY" ] && PY=python

# The SubagentStop payload (transcript_path, session_id, ...) arrives on stdin. Hand it to the
# parser, which reads the subagent's final message and appends iff it is a QA verdict. Bounded so a
# pathological transcript can never wedge the turn; every failure mode is swallowed (fail-open).
#
# Fail-open, but LOUD. `--hook` is total by contract (cisco_toolkit/scorecard.py :: main returns 0
# and swallows its own exceptions), so a NON-ZERO status here can only mean the recorder itself is
# gone — no interpreter, an import error, a renamed module, or the 30s timeout. Swallowing that
# silently is the failure mode that matters: the scorecard just stops growing, and the morning
# briefing keeps reporting "no entries", which reads as "no QA ran" rather than "the recorder is
# broken". Verified 2026-07-28: with a failing interpreter this hook emitted ZERO bytes. Still
# exit 0 — a broken recorder must never block a turn — but say so.
TIMEOUT=$(command -v timeout || true)
INPUT=$(cat 2>/dev/null || echo '{}')
if [ -n "$TIMEOUT" ]; then
  printf '%s' "$INPUT" | "$TIMEOUT" 30 "$PY" -m cisco_toolkit.scorecard --hook >/dev/null 2>&1
else
  printf '%s' "$INPUT" | "$PY" -m cisco_toolkit.scorecard --hook >/dev/null 2>&1
fi
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "scorecard-append: 'python -m cisco_toolkit.scorecard --hook' exited $rc — the QA scorecard is NOT being recorded (docs/quality/scorecard.jsonl will stop growing, and the briefing will keep saying 'no entries'). Allowing stop (fail-open)." >&2
fi
exit 0
