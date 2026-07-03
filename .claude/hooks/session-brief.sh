#!/usr/bin/env bash
# SessionStart hook — brief the engineer: toolkit version, branch, working-tree state,
# latest evidence snapshot, and a pointer to the ASNE roster + commands + doctrine.
# Cheap (no pytest). Fail-open: any error -> emit nothing, exit 0, so a session always starts.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0
PY=$(command -v python || command -v python3 || echo python)

ver=$(grep -E '^version *= *"' pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
export ASNE_VER="${ver:-?}"
export ASNE_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
export ASNE_DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_LAST="$(git log -1 --oneline 2>/dev/null)"
export ASNE_SNAP="$(ls -1t *.snapshot.json 2>/dev/null | head -1)"

"$PY" - <<'PYEOF' 2>/dev/null || true
import json, os
snap = os.environ.get("ASNE_SNAP") or "(none yet — run /assess)"
brief = (
    "Automated Senior Network Engineer — engagement context\n"
    f"- Toolkit version: {os.environ.get('ASNE_VER','?')} · branch: {os.environ.get('ASNE_BRANCH','?')} · uncommitted files: {os.environ.get('ASNE_DIRTY','0')}\n"
    f"- Last commit: {os.environ.get('ASNE_LAST','?')}\n"
    f"- Latest evidence snapshot: {snap}\n"
    "- Specialist roster (delegate to these): assessment-analyst, config-security-auditor, topology-reachability-analyst, design-author, mop-change-author, nrfu-validator, deliverable-qa-reviewer, release-captain\n"
    "- Commands: /assess /deliverables /audit /reachability /qa /release /ask\n"
    "- Doctrine: read-only by default; proposer != verifier; evidence-grounded & coverage-honest; no device writes; production change only via human-owned PR + CAB."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief}}))
PYEOF
exit 0
