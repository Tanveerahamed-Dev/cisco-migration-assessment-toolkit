#!/usr/bin/env bash
# PreToolUse hook (Bash|PowerShell) — the shell lane of ADR 0001 (P0-8).
# vault-guard.sh blocks the Write|Edit|NotebookEdit tools from touching C:\Vaults\brain;
# THIS hook closes the bypass those tools never see: a shell command whose string shows
# WRITE/DELETE intent against the vault (redirections > >>, tee, cp/mv/rm/rmdir/touch,
# sed -i, Set-Content/Out-File/Remove-Item, ...). Decision logic lives in
# vault_guard_bash.py next to this script (unit-tested by tests/test_vault_guard_bash.py).
# BEST-EFFORT pattern matching, not proof — obfuscated commands can evade; the hard floor
# remains the default permission mode (CLAUDE.md trust boundary; HR-005 residuals a/b).
# Reads are out of scope (ADR 0001 keeps the not-granted read rule as prose).
# Exit 2 blocks the tool call with the reason; every other outcome fails open (exit 0),
# so a hook bug or missing python never wedges a turn.
set -u
DIR=$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd) || DIR=".claude/hooks"
PY=$(command -v python || command -v python3 || echo python)
VERDICT=$("$PY" "$DIR/vault_guard_bash.py" 2>/dev/null || true)
case "$VERDICT" in
  BLOCK:*)
    echo "BLOCKED (ADR 0001, two-store rule): this shell command looks like a WRITE/DELETE into C:\Vaults\brain [${VERDICT#BLOCK:}] — repo sessions never write the vault. If this was a read-only command, drop or split the write-capable tokens (reads are not what this hook blocks). Capture lessons via /retro into docs/log.md (tag bridge-candidate); a separate vault-cwd session promotes them with /ingest." >&2
    exit 2
    ;;
esac
exit 0
