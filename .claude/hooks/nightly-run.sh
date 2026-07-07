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
# BEFORE YOU ARM IT (the live path is authored, not verified against your install):
#   * Confirm the `claude` flags below against YOUR CLI version (--max-turns, --permission-mode
#     plan). Budget is enforced EXTERNALLY by the daily ceiling + a per-run estimate — wire real
#     cost capture into the `--record` step before you trust the ceiling.
#   * To schedule it (only once trusted, per D5 "manual-trigger week 1"): register a Windows
#     Task Scheduler task whose action runs this script via git-bash. That is a system change —
#     do it yourself; this script will not.
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

# Caps (D5/D13). max-turns is a real claude flag; the USD budget is enforced externally by the
# daily ceiling in clock.py (a native per-invocation USD cap may not exist on your CLI version).
MAX_TURNS="${ASNE_NIGHTLY_MAX_TURNS:-12}"
CEILING="${ASNE_NIGHTLY_CEILING_USD:-2.0}"
EST_COST="${ASNE_NIGHTLY_EST_COST_USD:-0.5}"   # placeholder until real cost capture is wired

if [ "$MODE" = "dry-run" ]; then
  cat <<EOF
[nightly] DRY-RUN — nothing invoked, \$0 spent, ledger untouched.
Would invoke (ONLY with --live and ASNE_NIGHTLY_ARMED=yes):

  claude -p --max-turns ${MAX_TURNS} --permission-mode plan "<prompt below>"

Caps: max-turns=${MAX_TURNS}; daily ceiling=\$${CEILING} + 3-fail breaker + 30m cooldown (clock.py);
per-run cost estimate recorded to the ledger=\$${EST_COST} (until real cost capture is wired).

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
CLAUDE=$(command -v claude || echo "")
if [ -z "$CLAUDE" ]; then
  echo "[nightly] claude CLI not found on PATH — cannot run live. (Nothing spent.)"
  exit 0
fi

echo "[nightly] ARMED live run — invoking claude -p (propose-only, max-turns=${MAX_TURNS})..."
OUT=$("$CLAUDE" -p --max-turns "$MAX_TURNS" --permission-mode plan "$PROMPT" 2>&1); RC=$?
OUTCOME=$([ "$RC" -eq 0 ] && echo ok || echo fail)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")
# Record the outcome + (estimated) spend to the ledger so the breaker + daily ceiling stay honest.
printf '{"outcome":"%s","cost_usd":%s,"turns":%s,"actions":0,"commit":"%s","notes":"nightly live rc=%s"}' \
  "$OUTCOME" "$EST_COST" "$MAX_TURNS" "$COMMIT" "$RC" \
  | "$PY" -m cisco_toolkit.clock --record >/dev/null 2>&1 || true
echo "$OUT"
exit 0
