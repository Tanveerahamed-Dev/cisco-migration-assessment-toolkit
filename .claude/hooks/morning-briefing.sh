#!/usr/bin/env bash
# Morning-briefing assembler — the "what to look at today" digest, built from LOCAL repo
# state ONLY (no egress, no device access, no vault reads). Writes a dated briefing to
# docs/briefings/ and prints a readable digest. Manual today (via /briefing); wire into the
# SessionStart hook to make it automatic — Phase 6.1 of docs/autonomous-brain-plan-2026-07-06.md.
# Patterns mirror session-brief.sh (worktree-aware root, inline python, fail-open).
# Fail-open: any error on a metric -> that line is omitted/marked '?'; never blocks. exit 0.
set -u
for _name in $(compgen -e); do
  case "${_name^^}" in GIT_*) unset "$_name" ;; esac
done
GIT=$(type -P git 2>/dev/null || true)
[ -z "$GIT" ] && exit 0
cd "$("$GIT" rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null || exit 0
# Resolve an interpreter that RUNS — `command -v python` succeeds for the Microsoft Store stub,
# which exits 9009 and turns this briefing into a silent no-op. Fail-open behaviour is unchanged.
PY=""
for _c in python python3; do _p=$(command -v "$_c" 2>/dev/null) || continue
  if "$_p" -c "import sys" >/dev/null 2>&1; then PY="$_p"; break; fi; done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
  for _v in -3.12 -3; do _p=$(py "$_v" -c "import sys; print(sys.executable)" 2>/dev/null) || continue
    if [ -n "$_p" ] && [ -x "$_p" ]; then PY="$_p"; break; fi; done; fi
[ -z "$PY" ] && PY=python

ver=$(grep -E '^version *= *"' pyproject.toml 2>/dev/null | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
export ASNE_VER="${ver:-?}"
export ASNE_BRANCH="$("$GIT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
export ASNE_DIRTY="$("$GIT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_LAST="$("$GIT" log -1 --oneline 2>/dev/null)"
export ASNE_SNAP="$(ls -1t *.snapshot.json 2>/dev/null | head -1)"
export ASNE_GIT_COMMON="$("$GIT" rev-parse --git-common-dir 2>/dev/null || echo '')"
export ASNE_COMMITS_7D="$("$GIT" log --since='7 days ago' --oneline 2>/dev/null | wc -l | tr -d ' ')"
export ASNE_TODAY="$(date +%Y-%m-%d 2>/dev/null || echo '')"
export ASNE_BRIEF_MODE="${1:-}"   # "--session" -> emit SessionStart JSON; else raw markdown

# The assembler's output is CAPTURED rather than streamed, so an interpreter that never ran
# can be told apart from a clean repo. Measured 2026-07-29: with $PY broken, this block wrote
# 0 bytes to stdout, 0 to stderr and exited 0 — byte-identical to a healthy silent day, in
# BOTH raw and --session mode. "Absence rendered as health" is the one failure a briefing
# must never have. Still exit 0 (fail-open, a hook must never wedge a turn) — loud, not fatal.
BRIEF_OUT=$("$PY" - <<'PYEOF' 2>/dev/null
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
    root = main_root()
    try:
        graph_path = os.path.join(root, "graphify-out", "graph.json")
        topology_d = int((time.time() - os.path.getmtime(graph_path)) // 86400)
    except Exception:
        return None, "missing", False
    try:
        from cisco_toolkit.selfcheck import _guarded_refresh_time
        refreshed_at, error = _guarded_refresh_time(root)
        if refreshed_at is None or error:
            raise ValueError(error or "receipt absent")
        d = int((time.time() - refreshed_at) // 86400)
        return d, f"completed at this clean HEAD; graph bytes match receipt ({d}d ago; concurrent writers not excluded)", True
    except Exception:
        return topology_d, (f"topology write {topology_d}d old; guarded refresh currency unverified"), False

def lessons_queue():
    # !lesson bullets + LIFETIME bridge-candidate tags. This brief is vault-free (no /ingest
    # watermark), so it can only report the lifetime count, never pending — the honest,
    # watermarked pending queue lives in the SessionStart rot-watch. SSOT: one counter.
    txt = read("docs/log.md")
    les = len(re.findall(r"!lesson", txt))
    try:
        from cisco_toolkit.bridge_queue import bridge_queue_status
        life = bridge_queue_status(txt)["lifetime"]
    except Exception:
        life = len(re.findall(r"bridge-candidate", txt))
    return les, life

def open_items():
    hits = {}
    try:
        for f in glob.glob("docs/**/*.md", recursive=True):
            rf = f.replace("\\", "/")
            # Skip SELF-REFERENTIAL accumulations. Two of them, same disease as the "34 await
            # promotion" cry-wolf removed below:
            #   - our own emitted briefings (we would re-read yesterday's output as evidence);
            #   - docs/log.md, which is append-only NARRATIVE HISTORY. One retro sentence naming
            #     REC-6 kept it reported as an open item forever, with no status check anywhere —
            #     a monotonically-growing false positive. A log is not a state register.
            if "/briefings/" in rf or rf.endswith("docs/log.md"):
                continue
            t = read(f)
            for pat, label in ((r"\bGI-\d+", "GI"), (r"\bREC-\d+", "REC")):
                for m in re.findall(pat, t):
                    hits.setdefault(label, set()).add(m)
    except Exception:
        pass
    return {k: sorted(v) for k, v in hits.items()}

def todos():
    # Code-debt markers live in SOURCE. Scanning docs/ counted PROSE ABOUT markers and was pure
    # noise: 3 of the 4 it last reported came from ONE sentence asserting the census is zero
    # ("TODO/FIXME/HACK/XXX/stub/commented-out/bare-except all zero"), and the 4th from a retro
    # bullet using the word. Real code-debt count was 0. Every future retro mentioning "TODO"
    # would add another. Source globs only — a document discussing debt is not debt.
    n = 0; files = set()
    try:
        # SHIPPING source only. tests/ is deliberately excluded: a file ABOUT markers contains
        # markers, so tests/test_morning_briefing.py (which pins this very behaviour) re-poisoned
        # the count with 13 phantom hits the moment tests/ was included. Same trap one directory
        # over — the scanner must not be able to read its own guard as debt.
        seen = set()
        for pat in ("cisco_toolkit/**/*.py", "webapp/**/*.py", "portable/**/*.py", "*.py"):
            for f in glob.glob(pat, recursive=True):
                rf = f.replace("\\", "/")
                if rf in seen:
                    continue
                seen.add(rf)
                c = len(re.findall(r"\b(?:TODO|FIXME|XXX)\b", read(f)))
                if c:
                    n += c; files.add(rf)
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
        return "no entries yet — run /qa on a deliverable; it records the verdict in-session (scorecard --record)"
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

gday, gtxt, gverified = graph_age()
les, bc_life = lessons_queue()
oi = open_items()
td, tf = todos()
rows = scorecard_rows()
dirty = int(os.environ.get("ASNE_DIRTY", "0") or 0)
sc_verdict, sc_red = self_check()
intel_note = intel_status()

actions = []
if sc_verdict == "RED":
    actions.append(f"Agent-system self-check is RED — {sc_red or 'a guard/substrate check failed'} (fix before trusting the nerves)")
if not gverified:
    actions.append("Graph refresh currency is unverified — let the guarded Stop hook complete from a clean main checkout")
# No "await promotion" action here: this brief is vault-free (no /ingest watermark), so it cannot
# tell promoted from pending. The honest, watermarked pending count lives in the SessionStart
# rot-watch (session-brief.sh -> cisco_toolkit.bridge_queue). The cumulative count cried wolf here:
# it read "34 await promotion" on a day /ingest had already run that morning.
oi_flat = sum(len(v) for v in oi.values())
if oi_flat:
    actions.append(f"{oi_flat} open engagement item(s) (GI/REC) referenced in docs — check status")
if not rows:
    actions.append("Quality scorecard is empty — run `/qa` on a deliverable; it records each verdict in-session (scorecard --record) so the trend becomes a number you can watch")
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
L.append(f"- **Lessons**: {les} !lesson bullet(s); {bc_life} tagged bridge-candidate (lifetime; watermarked pending queue shown at SessionStart)")
if oi:
    L.append("- **Open items**: " + "; ".join(f"{k} {len(v)} ({', '.join(v[:6])}{'...' if len(v) > 6 else ''})" for k, v in sorted(oi.items())))
else:
    L.append("- **Open items**: none detected (GI-/REC- patterns in docs/, excluding the append-only log + our own briefings)")
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
) || true

if [ -n "$BRIEF_OUT" ]; then
  printf '%s\n' "$BRIEF_OUT"
else
  # DEGRADED: the assembler produced nothing. Say so on both streams, in the caller's format.
  _MSG="Morning briefing UNAVAILABLE - the assembler produced no output (python missing, or it raised before printing). NOTHING was measured: this is a degraded run, NOT a clean repo. Re-run: bash .claude/hooks/morning-briefing.sh"
  echo "[morning-briefing] $_MSG" >&2
  if [ "${ASNE_BRIEF_MODE:-}" = "--session" ]; then
    "$PY" -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.argv[1]}}))' "$_MSG" 2>/dev/null \
      || printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Morning briefing UNAVAILABLE - assembler produced no output. Nothing was measured; this is a degraded run, not a clean repo."}}'
  else
    printf '# Morning briefing - UNAVAILABLE\n\n%s\n' "$_MSG"
  fi
fi
exit 0
