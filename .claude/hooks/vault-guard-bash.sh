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
# Resolve an interpreter that actually RUNS, not merely one that resolves.
#
# `command -v python` SUCCEEDS for the Microsoft Store App-Execution-Alias stub, which prints
# "Python was not found" and exits 9009. Here that was not a visible error: the stub's stderr goes
# to /dev/null, `|| true` swallows the exit code, VERDICT is empty, no BLOCK:* case matches, and the
# hook exits 0 = ALLOW. **The vault guard silently stopped guarding whenever PATH carried only the
# stub** — and this box is exactly that box, while `py -3.12` works fine.
#
# Fail-open is deliberate and stays (see header). What changes is that it is now a LAST resort after
# a real search, and it is LOUD. A guard that is inert must say so; a silent one is indistinguishable
# from a guard that ran and approved, which is the whole false-health class this repo exists to
# refuse — and here it would read as "the vault write was checked and allowed".
PY=""
for _cand in python python3; do
  _p=$(command -v "$_cand" 2>/dev/null) || continue
  if "$_p" -c "import sys" >/dev/null 2>&1; then PY="$_p"; break; fi
done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
  for _v in -3.12 -3; do
    _p=$(py "$_v" -c "import sys; print(sys.executable)" 2>/dev/null) || continue
    if [ -n "$_p" ] && [ -x "$_p" ]; then PY="$_p"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "vault-guard-bash: no WORKING Python interpreter found (PATH may hold only Microsoft Store" >&2
  echo "stubs). The ADR-0001 vault write-guard did NOT run for this command — it is INERT, not" >&2
  echo "satisfied. The default permission mode remains the hard floor." >&2
  exit 0
fi
VERDICT=$("$PY" "$DIR/vault_guard_bash.py" 2>/dev/null || true)
case "$VERDICT" in
  BLOCK:*)
    echo "BLOCKED (ADR 0001, two-store rule): this shell command looks like a WRITE/DELETE into C:\Vaults\brain [${VERDICT#BLOCK:}] — repo sessions never write the vault. If this was a read-only command, drop or split the write-capable tokens (reads are not what this hook blocks). Capture lessons via /retro into docs/log.md (tag bridge-candidate); a separate vault-cwd session promotes them with /ingest." >&2
    exit 2
    ;;
esac
exit 0
