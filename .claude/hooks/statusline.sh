#!/usr/bin/env bash
# Status line — "<sat> ASNE vX.Y.Z <dot> <branch> <dot> <model>". Claude Code passes the
# status JSON (model / workspace / cost) on stdin; we capture it into an env var (NOT a stdin
# heredoc, which would collide with json reading) and pair it with the repo version + branch.
# Windows portability: the python -c source is PURE ASCII (glyphs built via chr(0x..), never
# literal), and stdout is forced to UTF-8 — else a piped cp1252 stdout raises UnicodeEncodeError
# on the emoji. Cheap & fail-open: any error prints an ASCII line and exits 0.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || true
PY=$(command -v python || command -v python3 || echo python)
ver=$(grep -E '^version *= *"' pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
export ASNE_VER="${ver:-?}"
export ASNE_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
export ASNE_INPUT="$(cat)"   # the status JSON arrives on stdin
export PYTHONUTF8=1

"$PY" -c '
import json, os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
model = ""
try:
    data = json.loads(os.environ.get("ASNE_INPUT") or "{}")
    model = (data.get("model") or {}).get("display_name") or ""
except Exception:
    pass
ver = os.environ.get("ASNE_VER", "?")
branch = os.environ.get("ASNE_BRANCH", "?")
sat = chr(0x1f6f0) + chr(0xfe0f)
sep = " " + chr(0xb7) + " "
parts = [sat + " ASNE v" + ver, branch]
if model:
    parts.append(model)
print(sep.join(parts))
' 2>/dev/null || echo "ASNE v${ASNE_VER}"
