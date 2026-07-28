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

PY=$(command -v python || command -v python3 || echo python)

# Fail open: if git can't tell us what changed, don't trap the user.
# The trailing `"?` matters: git QUOTES a porcelain path containing a space or a non-ASCII
# byte ("my probe.py"), so such a line ends in a quote, not in .py — and the gate silently
# stopped applying to exactly the files whose names are unusual. Fail-open on an unreadable
# git is deliberate; failing open on a NAME is not.
worktree=$(git status --porcelain 2>/dev/null | grep -E '\.py"?$' || true)

# ...and the COMMITTED changes on this branch. The working tree alone was the whole scope,
# so the gate went completely inert the moment a turn's Python changes were committed —
# which is the ordinary end-of-work action in this repo, not an edge case. Reproduced:
# uncommitted red suite -> exit 2 (blocks, correct); `git commit` the same files -> porcelain
# is empty -> exit 0 over the identical red suite. CLAUDE.md advertises this as blocking
# "after any .py change".
base=$(git rev-parse --verify -q '@{upstream}' 2>/dev/null \
       || git rev-parse --verify -q main 2>/dev/null || true)
committed=""
[ -n "$base" ] && committed=$(git diff --name-only "$base"...HEAD 2>/dev/null | grep -E '\.py$' || true)

[ -z "$worktree$committed" ] && exit 0

# Nothing has changed since the last GREEN run -> skip. This is what makes gating committed
# work affordable: without it, every turn on a feature branch carrying a .py commit would
# re-run the full ~2,000-test suite, including docs-only and question-only turns. The key
# covers HEAD, the porcelain status, the tracked diff CONTENT and every untracked file, so it
# moves whenever anything the suite would see moves. Any failure computing it degrades to
# "run the suite" — the safe direction.
statekey=$( { git rev-parse HEAD 2>/dev/null
              git status --porcelain 2>/dev/null
              git diff HEAD 2>/dev/null
              git ls-files -o --exclude-standard 2>/dev/null | while IFS= read -r f; do
                  printf '%s\n' "$f"; cat -- "$f" 2>/dev/null; done
            } | "$PY" -c 'import hashlib,sys;sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' 2>/dev/null || true)
marker="$(git rev-parse --git-dir 2>/dev/null || echo .git)/verify-green.ok"
if [ -n "$statekey" ] && [ -f "$marker" ] && [ "$(cat "$marker" 2>/dev/null)" = "$statekey" ]; then
  exit 0                         # already proven green for exactly this tree
fi

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
  # Record WHICH tree was proven green, so an unchanged follow-up turn skips the re-run.
  # Only ever written after a real exit-0 pytest run.
  [ -n "$statekey" ] && printf '%s' "$statekey" > "$marker" 2>/dev/null || true
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
