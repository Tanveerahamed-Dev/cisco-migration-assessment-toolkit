#!/usr/bin/env bash
# Stop hook — "iterate until green".
# If the working tree has CHANGED PYTHON FILES, run the test suite and BLOCK the
# turn from ending (exit 2) until it passes. No Python changes, or tests green ->
# allow the stop (exit 0). Heavy pytest output is kept out of context: only a
# short tail of the failure is handed back.
#
# Scope: gates on *.py only (pytest is this project's test runner). Frontend /
# .html / config changes are not gated here. Disable anytime via /hooks or by
# setting "disableAllHooks": true in settings. Claude Code releases the block
# automatically after 8 consecutive stops, so you can never get permanently stuck.
set -u

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0

# Fail open: if git can't tell us what changed, don't trap the user.
changed=$(git status --porcelain 2>/dev/null | grep -E '\.py$' || true)
[ -z "$changed" ] && exit 0

PY=$(command -v python || command -v python3 || echo python)
log=$(mktemp 2>/dev/null || echo "${TMP:-/tmp}/verify-green.$$")

if "$PY" -m pytest -q >"$log" 2>&1; then
  rm -f "$log"
  exit 0                       # green -> allow stop
fi

{
  echo "BLOCKED: pytest is failing after your Python changes — fix it before ending the turn."
  echo "Run 'python -m pytest' to see the full output. Summary (tail):"
  echo "--------------------------------------------------"
  tail -n 20 "$log"
} >&2
rm -f "$log"
exit 2                         # red -> block stop, feed the tail back to Claude
