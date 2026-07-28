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
PY=$(command -v python || command -v python3 || echo python)
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
