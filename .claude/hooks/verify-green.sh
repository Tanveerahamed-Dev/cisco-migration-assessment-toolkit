#!/usr/bin/env bash
# Stop hook — "iterate until green".
# If the working tree has CHANGED PYTHON FILES, run the test suite and BLOCK the
# turn from ending (exit 2) until it passes. No Python changes, or tests green ->
# allow the stop (exit 0). Heavy pytest output is kept out of context: only a
# short tail of the failure is handed back.
#
# Scope: gates on *.py only (pytest is this project's test runner). Frontend /
# .html / config changes are not gated here. Disable anytime via /hooks or by
# setting "disableAllHooks": true in settings. The pytest run is bounded by
# `timeout 540`; a timeout is RED because an incomplete suite proves nothing.
set -u

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0

# Resolve an interpreter that actually RUNS, not merely one that resolves.
#
# `command -v python` SUCCEEDS for the Microsoft Store App-Execution-Alias stub, so the old
# `python || python3 || echo python` chain short-circuited on it and never reached its fallbacks.
# The stub then prints "Python was not found" and exits 9009, which this hook reported as
# "BLOCKED: pytest is failing after your Python changes" — a FALSE RED that blocks every turn on
# evidence it never gathered, and points the reader at a bug that does not exist. Presence is not
# function; the same stub class silently killed three other hooks earlier in this review, and it
# recurred here the moment PATH stopped carrying a real install.
PY=""
for _cand in python python3; do
  _p=$(command -v "$_cand" 2>/dev/null) || continue
  if "$_p" -c "import sys" >/dev/null 2>&1; then PY="$_p"; break; fi
done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
  # The py launcher knows where real installs live even when PATH carries only stubs. Ask it for
  # an absolute executable, because $PY is used as a single command word below.
  for _v in -3.12 -3; do
    _p=$(py "$_v" -c "import sys; print(sys.executable)" 2>/dev/null) || continue
    if [ -n "$_p" ] && [ -x "$_p" ]; then PY="$_p"; break; fi
  done
fi
if [ -z "$PY" ]; then
  # Fail OPEN, loudly, and say plainly that nothing was verified. Silence here would be the
  # false-GREEN this hook exists to prevent; a false RED would be the mirror-image lie.
  echo "verify-green: no WORKING Python interpreter found (PATH may hold only Microsoft Store" >&2
  echo "stubs). Allowing the stop — the suite was NOT run, so this turn carries no test evidence." >&2
  exit 0
fi

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
VERIFY_SECONDS="${VERIFY_GREEN_TIMEOUT_SECONDS:-540}"

# Run the suite in parallel when pytest-xdist is present. This is a CORRECTNESS fix for this gate,
# not a speed-up: serially the suite takes 486-611s depending on machine load, so the 540s bound
# above sat INSIDE the variance band and blocked turns at random on a suite that passes. (Raising
# the bound is not an option — the hook ceiling is 600s.) Under `-n auto --dist loadfile` the same
# suite runs in ~166s. Verified id-for-id against a serial run via --junitxml: 5,015 testcases both
# ways, zero in either set only, both exit 0 — parallelism drops nothing.
#
# `--dist loadfile` keeps a module's tests on ONE worker. The default `load` scatters them, which
# would re-run each module-scoped fixture once per worker that receives one of its tests
# (test_phase_timings_contract's real `--redact` pipeline run is ~14s of setup).
#
# xdist is declared in pyproject's [dev], but degrade to serial when it is absent rather than
# passing `-n` to a pytest that does not understand it: that exits non-zero and this gate would
# report it as "pytest is failing" — the false RED the header warns about.
PARALLEL=""
if "$PY" -c 'import xdist' >/dev/null 2>&1; then
  PARALLEL="-n auto --dist loadfile"
fi
if [ -n "$TIMEOUT" ]; then
  # shellcheck disable=SC2086 - PARALLEL must word-split into separate argv entries
  "$TIMEOUT" "$VERIFY_SECONDS" "$PY" -m pytest -q $PARALLEL >"$log" 2>&1
else
  # shellcheck disable=SC2086
  "$PY" -m pytest -q $PARALLEL >"$log" 2>&1
fi
rc=$?

if [ "$rc" -eq 0 ]; then
  rm -f "$log"
  # Record WHICH tree was proven green, so an unchanged follow-up turn skips the re-run.
  # Only ever written after a real exit-0 pytest run.
  [ -n "$statekey" ] && printf '%s' "$statekey" > "$marker" 2>/dev/null || true
  exit 0                       # green -> allow stop
fi

if [ "$rc" -eq 124 ]; then
  echo "BLOCKED: pytest exceeded ${VERIFY_SECONDS}s; a partial suite is not green." >&2
  rm -f "$log"
  exit 2
fi

{
  echo "BLOCKED: pytest is failing after your Python changes — fix it before ending the turn."
  # Name the interpreter that was actually used: on this box bare `python` is a Store stub, so
  # the old hint handed the reader a command that cannot reproduce the run.
  echo "Run '$PY -m pytest' to see the full output. Summary (tail):"
  echo "--------------------------------------------------"
  tail -n 20 "$log"
} >&2
rm -f "$log"
exit 2                         # red -> block stop, feed the tail back to Claude
