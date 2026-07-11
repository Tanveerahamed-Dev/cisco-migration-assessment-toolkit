#!/usr/bin/env bash
# SessionStart hook — brief the engineer: toolkit version, branch, working-tree state,
# latest evidence snapshot, a pointer to the ASNE roster + commands + doctrine, and a
# "rot watch" (vault ingest/lint age, graphify graph age, memory sizes) so knowledge decay
# is visible at session start instead of discovered months later.
# Cheap (no pytest). Fail-open: any error -> emit nothing (or omit the metric), exit 0.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0
PY=$(command -v python || command -v python3 || echo python)

ver=$(grep -E '^version *= *"' pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
export ASNE_VER="${ver:-?}"
export ASNE_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
export ASNE_DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_LAST="$(git log -1 --oneline 2>/dev/null)"
export ASNE_SNAP="$(ls -1t *.snapshot.json 2>/dev/null | head -1)"
# graphify-out/ is untracked, so in a git worktree it exists only in the MAIN checkout;
# --git-common-dir points at the main .git from any worktree ('.git' in the main checkout).
export ASNE_GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null || echo '')"

"$PY" - <<'PYEOF' 2>/dev/null || true
import datetime, json, os, re, time

snap = os.environ.get("ASNE_SNAP") or "(none yet — run /assess)"

# --- rot watch (every metric independently fail-open) ---
def _days_since_op(op):
    # newest wiki/log.md line for the op: "## [YYYY-MM-DD] <op> — ..."
    try:
        txt = open(r"C:\Vaults\brain\wiki\log.md", encoding="utf-8", errors="replace").read()
        dates = re.findall(r"\[(\d{4}-\d{2}-\d{2})\]\s*" + op, txt)
        if not dates:
            return "never"
        return str((datetime.date.today() - datetime.date.fromisoformat(max(dates))).days) + "d ago"
    except Exception:
        return "?"

def _last_op_date(op):
    # the last YYYY-MM-DD stamped against <op> in the vault's own log = the /ingest watermark.
    # Same read the rot-watch age uses; None on any error/absence -> the bridge metric degrades.
    try:
        txt = open(r"C:\Vaults\brain\wiki\log.md", encoding="utf-8", errors="replace").read()
        dates = re.findall(r"\[(\d{4}-\d{2}-\d{2})\]\s*" + op, txt)
        return max(dates) if dates else None
    except Exception:
        return None

def _bridge():
    # HONEST repo->vault promotion backlog: NOT the cumulative bridge-candidate tag count (which
    # only grows and cries wolf), but lessons logged since the last /ingest. cisco_toolkit.bridge_queue.
    try:
        from cisco_toolkit.bridge_queue import bridge_queue_status
        st = bridge_queue_status(open("docs/log.md", encoding="utf-8", errors="replace").read(), _last_op_date("ingest"))
        p = st["pending"]
        if p is None:
            return "%d tagged (pending unknown)" % st["lifetime"]
        if p == 0:
            return "0 pending (%d lifetime)" % st["lifetime"]
        return "%d PENDING since /ingest %s -> run /ingest in a vault session" % (p, st["last_ingest"])
    except Exception:
        return "?"

def _main_root():
    # graphify freshness must be read from the MAIN checkout: graphify-out/ is untracked,
    # so a worktree session has none and would misreport "missing". ASNE_GIT_COMMON is the
    # main .git (absolute from a worktree; '.git' in the main checkout, which abspath
    # resolves against cwd). Fail-open to cwd if unset or unexpected.
    try:
        d = os.environ.get("ASNE_GIT_COMMON", "")
        if d:
            d = os.path.abspath(d)
            if os.path.basename(d) == ".git" and os.path.isdir(os.path.dirname(d)):
                return os.path.dirname(d)
    except Exception:
        pass
    return os.getcwd()

def _graph_age():
    try:
        d = int((time.time() - os.path.getmtime(os.path.join(_main_root(), "graphify-out", "graph.json"))) // 86400)
        return str(d) + "d old"
    except Exception:
        return "missing"

def _auto_memory():
    # auto-memory dir for THIS project (slug = abs path with :\/ -> -). Claude Code keys
    # auto-memory to the MAIN project's slug even in a worktree session, so slug from
    # _main_root(), not cwd (a .claude/worktrees/<name> slug has no memory dir and the
    # brief would misreport "dir 0KB; index 0 lines" while the real index has entries).
    try:
        slug = re.sub(r"[:\\/]", "-", _main_root())
        md = os.path.join(os.path.expanduser("~"), ".claude", "projects", slug, "memory")
        total = 0
        for root, _, files in os.walk(md):
            total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        idx = os.path.join(md, "MEMORY.md")
        lines = kb = 0
        if os.path.exists(idx):
            lines = sum(1 for _ in open(idx, encoding="utf-8", errors="replace"))
            kb = os.path.getsize(idx) // 1024
        return "dir %dKB; index %d lines/%dKB (startup boundary 200 lines/25KB)" % (total // 1024, lines, kb)
    except Exception:
        return "?"

def _agent_memory():
    # memory: project is set on the 3 author agents; growth failure is SILENT (GH #57507),
    # so surface it: 'none' after those agents have run = investigate.
    try:
        out = []
        for a in ("design-author", "mop-change-author", "release-captain"):
            p = os.path.join(".claude", "agent-memory", a, "MEMORY.md")
            out.append("%s %dKB" % (a, max(1, os.path.getsize(p) // 1024)) if os.path.isfile(p) else a + " none")
        return ", ".join(out)
    except Exception:
        return "?"

def _learnings():
    # distilled, verifiable engine facts (docs/quality/learnings.md) — surfaced so the durable
    # lessons are READ at session start, not rediscovered. Cheap count; fail-open.
    try:
        txt = open(os.path.join("docs", "quality", "learnings.md"), encoding="utf-8", errors="replace").read()
        n = sum(1 for l in txt.splitlines() if l.startswith("- "))
        m = len(txt.splitlines())
        return ("%d entries, %d/100 lines" % (n, m)) if n else "empty (no entries yet)"
    except Exception:
        return "none"

brief = (
    "Automated Senior Network Engineer — engagement context\n"
    f"- Toolkit version: {os.environ.get('ASNE_VER','?')} · branch: {os.environ.get('ASNE_BRANCH','?')} · uncommitted files: {os.environ.get('ASNE_DIRTY','0')}\n"
    f"- Last commit: {os.environ.get('ASNE_LAST','?')}\n"
    f"- Latest evidence snapshot: {snap}\n"
    f"- Rot watch: vault /ingest {_days_since_op('ingest')} · vault /lint {_days_since_op('lint')} (weekly per MASTER_PLAN §6) · graphify graph {_graph_age()} · bridge {_bridge()}\n"
    f"- Memory: {_auto_memory()} · agent-memory: {_agent_memory()}\n"
    f"- Learnings ({_learnings()}): distilled verifiable engine facts - read docs/quality/learnings.md\n"
    "- Specialist roster (delegate to these): assessment-analyst, config-security-auditor, topology-reachability-analyst, design-author, mop-change-author, nrfu-validator, deliverable-qa-reviewer, release-captain\n"
    "- Commands: /assess /deliverables /audit /reachability /qa /release /ask /retro\n"
    "- Doctrine: read-only by default; proposer != verifier; evidence-grounded & coverage-honest; no device writes; production change only via human-owned PR + CAB."
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief}}))
PYEOF
exit 0
