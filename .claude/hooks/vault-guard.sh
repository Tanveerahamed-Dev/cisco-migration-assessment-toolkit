#!/usr/bin/env bash
# PreToolUse hook (Write|Edit|NotebookEdit) — deterministic enforcement of ADR 0001
# (docs/decisions/0001-two-store-knowledge-architecture.md): repo sessions NEVER write the
# personal vault at C:\Vaults\brain. The bridge is one-way and sanitized — lessons leave this
# repo only as docs/log.md !lesson entries (tagged bridge-candidate via /retro) and are
# promoted by the vault's own /ingest in a separate vault-cwd session.
# The Bash/PowerShell command lane (redirections, tee/cp/mv/rm, Set-Content, ...) is
# covered by vault-guard-bash.sh + vault_guard_bash.py (P0-8).
# Exit 2 blocks the tool call with the reason; every other outcome fails open (exit 0),
# so a hook bug or missing python never wedges a turn.
#
# The decision NORMALISES the path before matching. Verified 2026-07-28 by running this hook
# against producer-generated payloads: matching only the two literal prefixes 'c:/vaults/brain'
# and '/c/vaults/brain' let four other spellings of the SAME file through with exit 0 —
# \\?\C:\Vaults\brain\x (Windows extended-length, which open() accepts), //c/Vaults/brain/x,
# /cygdrive/c/Vaults/brain/x, and any path reaching the vault through '..'. The shell lane
# (vault_guard_bash.py) already handled those spellings, so the Write|Edit lane was the weaker
# half of the same control. Recall-over-precision is retained deliberately: a prefix match still
# catches sibling names like C:/Vaults/brainstorm (over-block, never under-block).
#
# The python source is in SINGLE shell quotes with DOUBLE-quoted python literals, so no $,
# backtick or quote in it can ever be interpolated by the shell — the class that once silently
# broke the post-commit graph hook.
set -u
# Resolve an interpreter that actually RUNS, not merely one that resolves.
#
# `command -v python` SUCCEEDS for the Microsoft Store App-Execution-Alias stub, which prints
# "Python was not found" and exits 9009. The verdict below then comes back empty, no BLOCK case
# matches, and this hook exits 0 = ALLOW. Reproduced on this host with the tests running under Git
# Bash: a Write to the vault ROOT was ALLOWED (rc=0) with EMPTY stderr — the ADR-0001 write guard
# silently not guarding, and nothing anywhere saying so.
#
# Fail-open stays (a hook bug must never wedge a turn) but becomes a LAST resort after a real
# search, and it is LOUD. An inert guard that says nothing is indistinguishable from a guard that
# ran and approved the write.
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
  echo "vault-guard: no WORKING Python interpreter found (PATH may hold only Microsoft Store stubs)." >&2
  echo "The ADR-0001 vault write-guard did NOT run — it is INERT, not satisfied. The default" >&2
  echo "permission mode remains the hard floor." >&2
  exit 0
fi
VERDICT=$("$PY" -c 'import json,posixpath,sys
try:
    d=json.load(sys.stdin)
    t=d.get("tool_input") or {}
    p=str(t.get("file_path") or t.get("notebook_path") or "")
    p=p.replace(chr(92),"/").lower()
    for pre in ("//?/","//./"):
        if p.startswith(pre):
            p=p[len(pre):]
    if p.startswith("/cygdrive/"):
        p=p[10:]
    elif p.startswith("//"):
        p=p[2:]
    elif len(p)>2 and p[0]=="/" and p[2]=="/":
        p=p[1:]
    if len(p)>1 and p[0].isalpha() and p[1]=="/":
        p=p[0]+":"+p[1:]
    p=posixpath.normpath(p)
    if p.startswith("c:/vaults/brain"):
        sys.stdout.write("BLOCK")
except Exception:
    pass' 2>/dev/null || true)
if [ "$VERDICT" = "BLOCK" ]; then
  echo "BLOCKED (ADR 0001, two-store rule): repo sessions never write C:\Vaults\brain. Log the lesson via /retro into docs/log.md (tag it bridge-candidate); a separate vault-cwd session promotes it with /ingest." >&2
  exit 2
fi
exit 0
