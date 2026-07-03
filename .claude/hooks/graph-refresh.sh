#!/usr/bin/env bash
# Stop hook — keep the graphify knowledge graph fresh.
# If graphify-EXTRACTED source changed this turn, run `graphify update .` ONCE (AST-only,
# no API cost) so codebase queries stay accurate. This is MAINTENANCE, not a gate: it
# ALWAYS exits 0 (fail-open) — a stale or un-updatable graph must never block a turn.
# graphify is reached via `python -m graphify` because it is not on PATH here.
set -u

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0

# Nothing to update if the graph was never built.
[ -f graphify-out/graph.json ] || exit 0

# Only spend time if graphify-extracted CODE actually changed (not docs/config).
changed=$(git status --porcelain 2>/dev/null \
  | grep -Ei '\.(py|js|ts|tsx|jsx|mjs|cjs|go|rs|java|rb|c|h|cpp|hpp|cc|cs|kt|swift|php|scala|lua|html)$' \
  || true)
[ -z "$changed" ] && exit 0

PY=$(command -v python || command -v python3 || echo python)
TIMEOUT=$(command -v timeout || true)
log=$(mktemp 2>/dev/null || echo "${TMP:-/tmp}/graph-refresh.$$")

# Bound the run so a slow rebuild can never wedge the turn.
if [ -n "$TIMEOUT" ]; then
  "$TIMEOUT" 180 "$PY" -m graphify update . >"$log" 2>&1
else
  "$PY" -m graphify update . >"$log" 2>&1
fi
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "graph-refresh: 'python -m graphify update .' exited $rc (graph may be stale) — allowing stop (fail-open)." >&2
fi
rm -f "$log"
exit 0
