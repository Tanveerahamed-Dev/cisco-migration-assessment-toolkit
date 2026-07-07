#!/usr/bin/env bash
# Morning-briefing assembler — the "what to look at today" digest, built from LOCAL repo
# state ONLY (no egress, no device access, no vault reads). Writes a dated briefing to
# docs/briefings/ and prints a readable digest. Manual today (via /briefing); wire into the
# SessionStart hook to make it automatic — Phase 6.1 of docs/autonomous-brain-plan-2026-07-06.md.
# Patterns mirror session-brief.sh (worktree-aware root, inline python, fail-open).
# Fail-open: any error on a metric -> that line is omitted/marked '?'; never blocks. exit 0.
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0
PY=$(command -v python || command -v python3 || echo python)

ver=$(grep -E '^version *= *"' pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
export ASNE_VER="${ver:-?}"
export ASNE_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
export ASNE_DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_LAST="$(git log -1 --oneline 2>/dev/null)"
export ASNE_SNAP="$(ls -1t *.snapshot.json 2>/dev/null | head -1)"
export ASNE_GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null || echo '')"
export ASNE_COMMITS_7D="$(git log --since='7 days ago' --oneline 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_TODAY="$(date +%Y-%m-%d 2>/dev/null || echo '')"
export ASNE_BRIEF_MODE="${1:-}"   # "--session" -> emit SessionStart JSON; else raw markdown

"$PY" - <<'PYEOF' 2>/dev/null || true
import glob, json, os, re, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 console -> never crash on print
except Exception:
    pass

def main_root():
    # graphify-out/ is untracked -> lives only in the MAIN checkout; read graph age from
    # there, not a worktree cwd (which would misreport 'missing'). Mirrors session-brief.sh.
    try:
        d = os.environ.get("ASNE_GIT_COMMON", "")
        if d:
            d = os.path.abspath(d)
            if os.path.basename(d) == ".git" and os.path.isdir(os.path.dirname(d)):
                return os.path.dirname(d)
    except Exception:
        pass
    return os.getcwd()

def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""

def graph_age():
    try:
        d = int((time.time() - os.path.getmtime(os.path.join(main_root(), "graphify-out", "graph.json"))) // 86400)
        return d, (f"{d}d old" + ("  [!] stale (>7d) - run: python -m graphify update ." if d > 7 else ""))
    except Exception:
        return None, "missing"

def lessons_queue():
    txt = read("docs/log.md")
    return len(re.findall(r"!lesson", txt)), len(re.findall(r"bridge-candidate", txt))

def open_items():
    hits = {}
    try:
        for f in glob.glob("docs/**/*.md", recursive=True):
            if "/briefings/" in f.replace("\\", "/"):   # skip our OWN emitted briefings (self-reference)
                continue
            t = read(f)
            for pat, label in ((r"\bGI-\d+", "GI"), (r"\bREC-\d+", "REC")):
                for m in re.findall(pat, t):
                    hits.setdefault(label, set()).add(m)
    except Exception:
        pass
    return {k: sorted(v) for k, v in hits.items()}

def todos():
    n = 0; files = set()
    try:
        for f in glob.glob("docs/**/*.md", recursive=True) + glob.glob("cisco_toolkit/**/*.py", recursive=True):
            if "/briefings/" in f.replace("\\", "/"):    # skip our OWN emitted briefings (self-reference)
                continue
            c = len(re.findall(r"\b(?:TODO|FIXME|XXX)\b", read(f)))
            if c:
                n += c; files.add(f)
    except Exception:
        pass
    return n, len(files)

def scorecard_rows():
    try:
        return [json.loads(l) for l in read("docs/quality/scorecard.jsonl").splitlines() if l.strip()]
    except Exception:
        return []

def _scorecard_row(r):
    d, dl, sc, v = r.get("date", "?"), r.get("deliverable", "?"), r.get("score"), r.get("verdict", "?")
    if isinstance(sc, (int, float)):                       # eval-harness row: a numeric score
        return f"{d} {dl}={sc} ({v})"
    cx = r.get("counterexamples")                          # /qa-verdict row: no number -> show verdict+cx
    return f"{d} {dl} ({v}{f', {cx}cx' if isinstance(cx, int) else ''})"

def fmt_scorecard(rows):
    if not rows:
        return "no entries yet — records automatically once a /qa verdict is produced (SubagentStop appender)"
    tail = " | ".join(_scorecard_row(r) for r in rows[-3:])
    scored = [r.get("score") for r in rows if isinstance(r.get("score"), (int, float))]
    trend = ""
    if len(scored) >= 2:
        trend = "  (up) improving" if scored[-1] > scored[0] else ("  (down) regressing" if scored[-1] < scored[0] else "  (flat)")
    return tail + trend

def self_check():
    # Phase-4 agent-system self-check — RED leads the briefing. Fail-open (import/other error -> skipped).
    try:
        from cisco_toolkit.selfcheck import run_selfcheck
        r = run_selfcheck()
        red = [c for c in r["checks"] if c["status"] == "RED"]
        return r["verdict"], (f"{red[0]['name']}: {red[0]['detail']}" if red else "")
    except Exception:
        return None, ""

def intel_status():
    # Phase-5 intel-feed status (no-egress consumer). Empty/absent -> honest "gated" note.
    try:
        from cisco_toolkit.intel_feed import load_feeds
        return load_feeds().get("note", "")
    except Exception:
        return ""

gday, gtxt = graph_age()
les, bc = lessons_queue()
oi = open_items()
td, tf = todos()
rows = scorecard_rows()
dirty = int(os.environ.get("ASNE_DIRTY", "0") or 0)
sc_verdict, sc_red = self_check()
intel_note = intel_status()

actions = []
if sc_verdict == "RED":
    actions.append(f"Agent-system self-check is RED — {sc_red or 'a guard/substrate check failed'} (fix before trusting the nerves)")
if gday is not None and gday > 7:
    actions.append("Graph is stale (>7d) — refresh: `python -m graphify update .`")
if bc:
    actions.append(f"{bc} bridge-candidate lesson(s) await vault promotion — run `/ingest` in a vault session")
oi_flat = sum(len(v) for v in oi.values())
if oi_flat:
    actions.append(f"{oi_flat} open engagement item(s) (GI/REC) referenced in docs — check status")
if not rows:
    actions.append("Quality scorecard is empty — run `/qa` on a deliverable; the SubagentStop appender records each verdict so the trend becomes a number you can watch")
if dirty:
    actions.append(f"{dirty} uncommitted file(s) — review/commit")
if not actions:
    actions.append("Nothing flagged — clean. Pull the next item from docs/autonomous-brain-plan-2026-07-06.md.")

today = os.environ.get("ASNE_TODAY") or "today"
snap = os.environ.get("ASNE_SNAP") or "(none yet — run /assess)"

L = []
L.append(f"# Morning briefing — {today}")
L.append("")
L.append(f"**Toolkit** {os.environ.get('ASNE_VER','?')} · **branch** {os.environ.get('ASNE_BRANCH','?')} · **uncommitted** {dirty} · **commits (7d)** {os.environ.get('ASNE_COMMITS_7D','?')}")
L.append(f"**Last commit** {os.environ.get('ASNE_LAST','?')}")
L.append(f"**Latest evidence snapshot** {snap}")
L.append("")
L.append("## >> What to look at today")
L += [f"- {a}" for a in actions]
L.append("")
L.append("## Signals")
L.append(f"- **Graph**: {gtxt}")
L.append(f"- **Lessons**: {les} !lesson bullet(s); {bc} tagged bridge-candidate (promotion queue depth)")
if oi:
    L.append("- **Open items**: " + "; ".join(f"{k} {len(v)} ({', '.join(v[:6])}{'...' if len(v) > 6 else ''})" for k, v in sorted(oi.items())))
else:
    L.append("- **Open items**: none detected (GI-/REC- patterns in docs/)")
L.append(f"- **TODO/FIXME**: {td} across {tf} file(s)")
L.append(f"- **Quality scorecard**: {fmt_scorecard(rows)}")
if sc_verdict:
    L.append(f"- **Self-check**: {sc_verdict}" + (f" — {sc_red}" if sc_red else ""))
if intel_note:
    L.append(f"- **Intel feed**: {intel_note}")
L.append("")
L.append("_Assembled from local repo state only — no egress, no device access. Manual today; wire into SessionStart to make it automatic (docs/autonomous-brain-plan-2026-07-06.md §6.1)._")

brief = "\n".join(L)
try:
    os.makedirs("docs/briefings", exist_ok=True)
    open(os.path.join("docs", "briefings", f"briefing-{today}.md"), "w", encoding="utf-8").write(brief + "\n")
except Exception:
    pass
if os.environ.get("ASNE_BRIEF_MODE") == "--session":
    # injected as context at session start; json.dumps ascii-escapes -> cp1252-safe
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief}}))
else:
    print(brief)
PYEOF
exit 0
