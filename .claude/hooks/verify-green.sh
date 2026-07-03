#!/usr/bin/env bash
# Stop hook — "iterate until green".
# If the working tree has CHANGED PYTHON FILES, run the test suite and BLOCK the
# turn from ending (exit 2) until it passes. No Python changes, or tests green ->
# allow the stop (exit 0). Heavy pytest output is kept out of context: only a
# short tail of the failure is handed back.
#
# Scope: gates on *.py only (pytest is this project's test runner). Frontend /
# .html / config changes are not gated here. Disable anytime via /hooks or by
# setting "disableAllHooks": true in settings. Backstops against getting stuck:
# the pytest run is bounded by `timeout 540` (fails OPEN if exceeded), and the
# Stop hook itself has a 600s ceiling.
set -u

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0

# Fail open: if git can't tell us what changed, don't trap the user.
changed=$(git status --porcelain 2>/dev/null | grep -E '\.py$' || true)
[ -z "$changed" ] && exit 0

PY=$(command -v python || command -v python3 || echo python)
log=$(mktemp 2>/dev/null || echo "${TMP:-/tmp}/verify-green.$$")

# Bound the run so a hung or pathologically slow test can never wedge the turn:
# fail OPEN on timeout (exit 0) instead of blocking until the 600s hook ceiling.
TIMEOUT=$(command -v timeout || true)
if [ -n "$TIMEOUT" ]; then
  "$TIMEOUT" 540 "$PY" -m pytest -q >"$log" 2>&1
else
  "$PY" -m pytest -q >"$log" 2>&1
fi
rc=$?

if [ "$rc" -eq 0 ]; then
  rm -f "$log"
  exit 0                       # green -> allow stop
fi

if [ "$rc" -eq 124 ]; then     # timed out -> fail open so a hang never wedges the turn
  echo "verify-green: pytest exceeded 540s and was terminated — allowing stop (fail-open)." >&2
  rm -f "$log"
  exit 0
fi

{
  echo "BLOCKED: pytest is failing after your Python changes — fix it before ending the turn."
  echo "Run 'python -m pytest' to see the full output. Summary (tail):"
  echo "--------------------------------------------------"
  tail -n 20 "$log"
} >&2
rm -f "$log"
exit 2                         # red -> block stop, feed the tail back to Claude
