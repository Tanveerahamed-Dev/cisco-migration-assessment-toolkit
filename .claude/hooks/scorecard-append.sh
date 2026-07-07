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

PY=$(command -v python || command -v python3 || echo python)

# The SubagentStop payload (transcript_path, session_id, ...) arrives on stdin. Hand it to the
# parser, which reads the subagent's final message and appends iff it is a QA verdict. Bounded so a
# pathological transcript can never wedge the turn; every failure mode is swallowed (fail-open).
TIMEOUT=$(command -v timeout || true)
INPUT=$(cat 2>/dev/null || echo '{}')
if [ -n "$TIMEOUT" ]; then
  printf '%s' "$INPUT" | "$TIMEOUT" 30 "$PY" -m cisco_toolkit.scorecard --hook >/dev/null 2>&1 || true
else
  printf '%s' "$INPUT" | "$PY" -m cisco_toolkit.scorecard --hook >/dev/null 2>&1 || true
fi
exit 0
