#!/usr/bin/env bash
# PreToolUse hook (Write|Edit|NotebookEdit) — deterministic enforcement of ADR 0001
# (docs/decisions/0001-two-store-knowledge-architecture.md): repo sessions NEVER write the
# personal vault at C:\Vaults\brain. The bridge is one-way and sanitized — lessons leave this
# repo only as docs/log.md !lesson entries (tagged bridge-candidate via /retro) and are
# promoted by the vault's own /ingest in a separate vault-cwd session.
# Exit 2 blocks the tool call with the reason; every other outcome fails open (exit 0),
# so a hook bug or missing python never wedges a turn.
set -u
PY=$(command -v python || command -v python3 || echo python)
VERDICT=$("$PY" -c "import json,sys
try:
    d=json.load(sys.stdin)
    t=d.get('tool_input') or {}
    p=str(t.get('file_path') or t.get('notebook_path') or '')
    p=p.replace(chr(92),'/').lower()
    if p.startswith('c:/vaults/brain') or p.startswith('/c/vaults/brain'):
        sys.stdout.write('BLOCK')
except Exception:
    pass" 2>/dev/null || true)
if [ "$VERDICT" = "BLOCK" ]; then
  echo "BLOCKED (ADR 0001, two-store rule): repo sessions never write C:\Vaults\brain. Log the lesson via /retro into docs/log.md (tag it bridge-candidate); a separate vault-cwd session promotes it with /ingest." >&2
  exit 2
fi
exit 0
