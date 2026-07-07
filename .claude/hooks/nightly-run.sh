#!/usr/bin/env bash
# =============================================================================================
# Nightly propose-only run — MANUAL TRIGGER, DRY-RUN BY DEFAULT.  Phase 2 of
# docs/autonomous-brain-plan-v4-final-2026-07-06.md ("the clock").
#
# WHAT THIS IS: the reviewable wrapper a nightly `claude -p` pass WOULD use. It is deliberately
# NOT registered as a hook and NOT scheduled — you run it by hand. By default it SPENDS NOTHING:
# it prints exactly what it would invoke and stands down. The live path exists but is
# DOUBLE-GUARDED (needs `--live` AND `ASNE_NIGHTLY_ARMED=yes`) so it cannot spend by accident.
#
# SAFETY MODEL (all carried from the plan, non-negotiable):
#   * PROPOSE-ONLY — output is a briefing + at most reviewable suggestions; never a device write,
#     never `git push`, never a merge, never bypassPermissions.
#   * PREFLIGHT-GATED — runs `cisco_toolkit.clock --preflight` first (3-fail breaker + 30m
#     cooldown + daily-spend ceiling, D5/D13). NO-GO -> stand down, exit 0, spend $0.
#   * FAIL-OPEN — any error stands down; it never wedges anything and never spends on error.
#
# USAGE:
#   bash .claude/hooks/nightly-run.sh            # DRY-RUN (default): print the plan, spend $0
#   bash .claude/hooks/nightly-run.sh --live     # still refuses unless ASNE_NIGHTLY_ARMED=yes
#   ASNE_NIGHTLY_ARMED=yes bash .claude/hooks/nightly-run.sh --live   # ARMED: spends metered $
#
# BEFORE YOU ARM IT — VERIFIED against this install (claude-code 2.1.202, 2026-07-07):
#   * FLAGS CONFIRMED: this CLI has --print, --output-format json, --permission-mode plan, and a
#     NATIVE --max-budget-usd per-run hard cap. It has NO --max-turns (that flag was dropped here).
#     Real per-run cost is now captured from the JSON `total_cost_usd` (the old $0.5 estimate is gone).
#   * CLI PATH: `claude` is NOT on PATH under the Windows desktop app, which bundles it at
#     <Roaming>/Claude/claude-code/<version>/claude.exe — resolved below (newest version wins).
#   * AUTH IS THE REMAINING PREREQUISITE: the bundled CLI is NOT logged in for headless use (a probe
#     returned "Not logged in"). Provide ANTHROPIC_API_KEY (metered, D13 separate pool) in the
#     environment the run/scheduler uses, OR run `claude /login`. Until then a live run records
#     'skipped' (spends $0, never trips the breaker) and tells you how to fix it.
#   * To schedule it (only once trusted, per D5 "manual-trigger week 1"): register a Windows Task
#     Scheduler task that runs this script via git-bash WITH ANTHROPIC_API_KEY in its environment.
#     That is a system change — do it yourself; this script will not.
# =============================================================================================
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0
PY=$(command -v python || command -v python3 || echo python)

MODE="dry-run"
for a in "$@"; do
  case "$a" in
    --live) MODE="live" ;;
    --dry-run) MODE="dry-run" ;;
    *) ;;
  esac
done

# 1) PREFLIGHT — the two rails. Bail (no-op, exit 0) on NO-GO. `--preflight` exits 0=GO / 3=NO-GO.
PF=$("$PY" -m cisco_toolkit.clock --preflight 2>/dev/null); PF_RC=$?
echo "$PF"
if [ "$PF_RC" -ne 0 ]; then
  echo "[nightly] preflight NO-GO (rc=$PF_RC) — standing down. Nothing run, \$0 spent."
  exit 0
fi

# 2) Assemble the local, no-egress briefing payload (read-only). Skippable for a fast/hermetic run.
if [ "${ASNE_NIGHTLY_NO_BRIEF:-}" = "1" ]; then
  BRIEF="(briefing assembly skipped: ASNE_NIGHTLY_NO_BRIEF=1)"
else
  BRIEF=$(bash .claude/hooks/morning-briefing.sh 2>/dev/null || echo "(briefing assembler produced nothing)")
fi

# 2b) Agent-system self-check (Phase 4) — local, free, no egress. RED leads the briefing.
SELFCHECK=$("$PY" -m cisco_toolkit.selfcheck 2>/dev/null || echo "(self-check unavailable)")

# 3) The propose-only prompt the nightly hands to claude -p. Scoped to what exists TODAY (Phase 2):
#    assemble the briefing, surface open items, name the single next move — all read-only.
#    (Phase 4 will add: run the eval smoke tier + the agent-system self-check to this payload.)
PROMPT="You are the nightly PROPOSE-ONLY senior-network-engineer pass. HARD CONSTRAINTS: read-only;
never write to a device; never git push, never merge, never bypassPermissions; ground every claim in
local evidence ('not observed' is never 'healthy'). Using the briefing payload below, produce a
<=1-screen morning briefing where every line is a number or a link, then name the single
highest-impact next move. Propose only — your output is a briefing plus at most reviewable
suggestions, never an applied change.

--- agent-system self-check (RED items lead the briefing) ---
${SELFCHECK}

--- briefing payload (local, no-egress) ---
${BRIEF}"

# Caps (D5/D13), VERIFIED against the installed CLI (claude-code 2.1.202):
#   * NO --max-turns on this CLI (dropped) — spend is bounded by the NATIVE --max-budget-usd hard
#     cap PER RUN (below) plus the external daily ceiling in clock.py.
#   * real per-run cost is captured from --output-format json (`total_cost_usd`) — no estimate.
MAX_BUDGET_USD="${ASNE_NIGHTLY_MAX_BUDGET_USD:-0.50}"   # native per-run hard cap (claude --max-budget-usd)
CEILING="${ASNE_NIGHTLY_CEILING_USD:-2.0}"              # external daily ceiling (clock.py)

# Resolve the claude CLI. It is NOT on PATH under the Windows desktop app, which bundles it at
# <Roaming>/Claude/claude-code/<version>/claude.exe — resolve the NEWEST version (survives app updates).
resolve_claude() {
  local c roam
  c=$(command -v claude 2>/dev/null) && { printf '%s' "$c"; return 0; }
  roam="${APPDATA:-$HOME/AppData/Roaming}"
  c=$(ls -d "$roam"/Claude/claude-code/*/claude.exe 2>/dev/null | sort -V | tail -1)
  [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}
CLAUDE=$(resolve_claude || echo "")

if [ "$MODE" = "dry-run" ]; then
  cat <<EOF
[nightly] DRY-RUN — nothing invoked, \$0 spent, ledger untouched.
Resolved claude CLI: ${CLAUDE:-"(NOT FOUND — set PATH or install)"}
Would invoke (ONLY with --live and ASNE_NIGHTLY_ARMED=yes):

  claude -p --output-format json --max-budget-usd ${MAX_BUDGET_USD} --permission-mode plan "<prompt below>"

Caps: per-run hard cap=\$${MAX_BUDGET_USD} (native --max-budget-usd); daily ceiling=\$${CEILING}
      + 3-fail breaker + 30m cooldown (clock.py). Real cost captured from JSON total_cost_usd.
NOTE: headless auth is required — an unauthenticated CLI returns "Not logged in" and is recorded as
      'skipped' (never trips the breaker). Set ANTHROPIC_API_KEY (D13 metered pool) or run 'claude /login'.

----- prompt -----
${PROMPT}
------------------
EOF
  exit 0
fi

# ---------------------------------- LIVE PATH (spends metered $) ------------------------------
# Second guard: --live alone is not enough; you must also arm it. This makes accidental spend
# (a stray --live in a script) a no-op.
if [ "${ASNE_NIGHTLY_ARMED:-}" != "yes" ]; then
  echo "[nightly] --live requested but ASNE_NIGHTLY_ARMED != yes — refusing to spend."
  echo "          To arm: ASNE_NIGHTLY_ARMED=yes bash .claude/hooks/nightly-run.sh --live"
  exit 0
fi
if [ -z "$CLAUDE" ]; then
  echo "[nightly] claude CLI not found (not on PATH, no desktop-app bundle) — cannot run live. (Nothing spent.)"
  exit 0
fi

echo "[nightly] ARMED live run — invoking $(basename "$CLAUDE") -p (propose-only, plan mode, --max-budget-usd=${MAX_BUDGET_USD})..."
# </dev/null avoids the CLI's slow-stdin warning; 2>/dev/null keeps RAW as clean single-result JSON.
RAW=$("$CLAUDE" -p --output-format json --max-budget-usd "$MAX_BUDGET_USD" --permission-mode plan "$PROMPT" </dev/null 2>/dev/null); RC=$?

# Parse the JSON for REAL cost + turns + error status (coverage-honest: unparseable => treated as fail).
PARSED=$(printf '%s' "$RAW" | "$PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
    cost = d.get("total_cost_usd", 0) or 0
    turns = d.get("num_turns", 0) or 0
    err = bool(d.get("is_error", True))
    res = (d.get("result") or "").replace("\n", " ").replace("\t", " ")[:160]
    print(f"{cost}\t{turns}\t{str(err).lower()}\t{res}")
except Exception:
    print("0\t0\ttrue\tunparseable-cli-output")
')
COST=$(printf '%s' "$PARSED" | cut -f1); COST="${COST:-0}"
TURNS=$(printf '%s' "$PARSED" | cut -f2); TURNS="${TURNS:-0}"
ISERR=$(printf '%s' "$PARSED" | cut -f3)
RESULT=$(printf '%s' "$PARSED" | cut -f4-)

# Classify. An UNAUTHENTICATED CLI ("Not logged in") is a config gap, not a run failure -> 'skipped'
# so a missing credential can't trip the breaker; a real run is ok iff exit 0 AND is_error=false.
if [ "$ISERR" = "true" ] && printf '%s' "$RESULT" | grep -qiE "not logged in|/login|please run.*login"; then
  OUTCOME="skipped"
  echo "[nightly] claude is NOT authenticated for headless use -> \"$RESULT\". Recorded 'skipped', \$0 spent."
  echo "          Fix: set ANTHROPIC_API_KEY (metered, D13 separate pool) OR run 'claude /login', then re-arm."
elif [ "$RC" -eq 0 ] && [ "$ISERR" = "false" ]; then
  OUTCOME="ok"
else
  OUTCOME="fail"
fi
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")

# Record the outcome + REAL spend to the ledger so the breaker + daily ceiling stay honest.
printf '{"outcome":"%s","cost_usd":%s,"turns":%s,"actions":0,"commit":"%s","notes":"nightly %s rc=%s"}' \
  "$OUTCOME" "$COST" "$TURNS" "$COMMIT" "$OUTCOME" "$RC" \
  | "$PY" -m cisco_toolkit.clock --record >/dev/null 2>&1 || true

# Surface the model's briefing (the JSON `result`) on a successful run.
if [ "$OUTCOME" = "ok" ]; then
  printf '%s' "$RAW" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("result",""))' 2>/dev/null || true
fi
echo "[nightly] outcome=$OUTCOME  cost=\$$COST  turns=$TURNS"
exit 0
