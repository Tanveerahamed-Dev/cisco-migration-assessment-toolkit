"""The automation that GATES everything else, EXECUTED — not grepped.

Companion to tests/test_ci_gates.py, which pins the verify-green Stop hook. Everything under
.claude/ is what the project's verification posture actually rests on, yet before this file only
verify-green.sh, morning-briefing.sh, nightly-run.sh and vault-guard-bash.sh were ever run by a
test; graph-refresh.sh, scorecard-append.sh, vault-guard.sh and *every hook command embedded in
.claude/settings.json* were pinned by nothing at all.

That is exactly how the defects below survived (all four reproduced 2026-07-28):

* settings.json invoked a bare ``python3``. On this Windows box ``python3`` resolves to the
  Microsoft Store App-Execution-Alias stub, which prints "Python was not found" and exits 49 —
  so the UserPromptSubmit protocol injection and both graphify PreToolUse hints emitted ZERO
  bytes on every single invocation, for months, while reporting success (``|| true``).
* graph-refresh.sh carried the same quoted-path miss verify-green.sh was fixed for: git QUOTES a
  porcelain path containing a space or a non-ASCII byte, so the line ends in ``"`` and not in
  ``.py``, and the knowledge graph silently stopped refreshing for exactly those files.
* scorecard-append.sh swallowed a completely dead recorder in total silence (0 bytes, exit 0).
* vault-guard.sh — the Write|Edit lane of ADR 0001 — matched two literal path prefixes, so four
  other spellings of the same vault file (extended-length ``\\\\?\\``, ``//c/``, ``/cygdrive/c/``,
  and anything reaching the vault through ``..``) were let through with exit 0, while the shell
  lane next door already handled them.

Method notes for anyone extending this file:

* Payloads are written with ``json.dump`` to a FILE and fed to the hook via stdin redirection.
  Do NOT pass a Windows path through argv on this platform: the MSYS/Cygwin argv converter
  silently rewrote ``\\\\?\\C:\\...`` to ``\\?\\C:\\...`` and ``/cygdrive/c/...`` to
  ``C:/Program Files/Git/cygdrive/c/...`` mid-flight, which manufactures a passing hook out of a
  mangled fixture.
* To make an interpreter subprocess fail DETERMINISTICALLY without touching PATH, shadow the
  target module through ``PYTHONPATH`` (it precedes site-packages). ``_pythonpath_shim`` builds
  a package whose ``__main__`` exits with a chosen code.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".claude", "hooks")

def _resolve_bash():
    found = shutil.which("bash")
    if found or os.name != "nt":
        return found
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA"),
    ]
    for root in filter(None, roots):
        for relative in (("Git", "bin", "bash.exe"), ("Programs", "Git", "bin", "bash.exe")):
            candidate = os.path.join(root, *relative)
            if os.path.isfile(candidate):
                return candidate
    return None


_BASH = _resolve_bash()
_GIT = shutil.which("git")
_needs_shell = pytest.mark.skipif(not (_BASH and _GIT), reason="bash / git unavailable")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _settings():
    return json.loads(_read(".claude", "settings.json"))


def _hook_commands(settings):
    """Every ``type: command`` string in settings.json, as (event, index, command)."""
    out = []
    for event, entries in (settings.get("hooks") or {}).items():
        for i, entry in enumerate(entries):
            for h in entry.get("hooks", []):
                if h.get("type") == "command":
                    out.append((event, i, h["command"]))
    sl = settings.get("statusLine") or {}
    if sl.get("type") == "command":
        out.append(("statusLine", 0, sl["command"]))
    return out


def _payload(tmp_path, name, obj):
    p = tmp_path / (name + ".json")
    with open(p, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f)
    return p


def _run_command_string(command, payload_path, cwd=ROOT, env=None):
    """Run a settings.json command string the way Claude Code does: as a shell command with the
    hook payload on stdin. Written to a file first so no quoting layer can alter it."""
    script = os.path.join(os.path.dirname(payload_path), "cmd.sh")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(command + "\n")
    with open(payload_path, "rb") as stdin:
        return subprocess.run([_BASH, script], cwd=cwd, stdin=stdin, capture_output=True,
                              text=True, timeout=180, env=env)


def _run_hook(name, payload_path=None, cwd=ROOT, env=None):
    hook = os.path.join(HOOKS, name)
    stdin = open(payload_path, "rb") if payload_path else subprocess.DEVNULL
    try:
        return subprocess.run([_BASH, hook], cwd=str(cwd), stdin=stdin, capture_output=True,
                              text=True, timeout=300, env=env)
    finally:
        if payload_path:
            stdin.close()


def _pythonpath_shim(tmp_path, package, module, exit_code):
    """A dir suitable for PYTHONPATH in which ``python -m <package>[.<module>]`` exits
    ``exit_code``. Shadows the real package, so the hook's own interpreter resolution is left
    completely untouched — the failure is injected in the module, not in PATH."""
    d = tmp_path / ("shim_%s" % package)
    pkg = d / package
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / ("%s.py" % module if module else "__main__.py")).write_text(
        "raise SystemExit(%d)\n" % exit_code, encoding="utf-8")
    if module:
        (pkg / "__main__.py").write_text("raise SystemExit(%d)\n" % exit_code, encoding="utf-8")
    return str(d)


def _env_with(**extra):
    env = dict(os.environ)
    env.update(extra)
    return env


def _git_repo(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run([_GIT, "init", "-q"], cwd=str(repo), check=True)
    subprocess.run([_GIT, "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
    subprocess.run([_GIT, "config", "user.name", "t"], cwd=str(repo), check=True)
    return repo


# ------------------------------------------------------------------ settings.json, EXECUTED
# Nothing in the suite read this file before. Every hook Claude Code actually fires for this
# project is declared here, and three of them were dead.

def test_no_settings_hook_invokes_a_bare_python3():
    """`python3` is not a portable interpreter name. On this project's primary dev OS it is the
    Microsoft Store App-Execution-Alias stub: on PATH, exits 49, produces nothing.

    Hooks must resolve an interpreter that RUNS — probe each candidate with `-c "import sys"` and
    fall back to the `py` launcher — as every `.claude/hooks/*.sh` script and the inline
    settings.json commands now do.

    This docstring used to name `command -v python || command -v python3` as the pattern to copy.
    That is PRESENCE, not function, and `command -v` succeeds for the stub — it was the defect, not
    the remedy, and it silently disabled the ADR-0001 vault write-guard among others. A guard whose
    prose recommends the bug it exists to prevent will eventually be obeyed."""
    offenders = []
    for event, i, cmd in _hook_commands(_settings()):
        # A leading/standalone `python3 ...` invocation, as opposed to `command -v python3`.
        for token in ("python3 -c", "python3 -m", "| python3", "; python3", "&& python3"):
            if cmd.lstrip().startswith("python3 ") or token in cmd:
                offenders.append("%s[%d]: %s" % (event, i, cmd[:80]))
                break
    assert not offenders, (
        "settings.json hook(s) invoke a bare python3, which is a non-functional Store stub on "
        "Windows — these hooks silently emit nothing: " + "; ".join(offenders))


@_needs_shell
def test_user_prompt_submit_hook_actually_injects_the_protocol(tmp_path):
    """The UserPromptSubmit hook's whole job is to hand .claude/fullpower-max-default.md back as
    additionalContext. It emitted 0 bytes on every prompt while exiting 0."""
    settings = _settings()
    cmd = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    payload = _payload(tmp_path, "ups", {"hook_event_name": "UserPromptSubmit", "prompt": "hi"})
    p = _run_command_string(cmd, payload)
    assert p.stdout.strip(), (
        "the UserPromptSubmit hook emitted NOTHING — the protocol injection is a silent no-op "
        "(stderr=%r)" % p.stderr[-300:])
    out = json.loads(p.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert ctx.strip() == _read(".claude", "fullpower-max-default.md").strip(), \
        "injected context is not the protocol file"


@_needs_shell
def test_pretooluse_graphify_hints_actually_fire(tmp_path):
    """Both graphify hint hooks parse the tool payload with an interpreter. When that interpreter
    is dead they degrade to 'no hint, ever' — indistinguishable from 'the payload did not match'.
    Positive AND negative case, so a hook that unconditionally echoes cannot pass either."""
    cmds = [e["hooks"][0]["command"] for e in _settings()["hooks"]["PreToolUse"]]
    bash_hint = [c for c in cmds if "additionalContext" in c and "grep" in c]
    read_hint = [c for c in cmds if "additionalContext" in c and "file_path" in c]
    assert bash_hint and read_hint, "the graphify PreToolUse hint hooks are gone from settings.json"

    hint_repo = tmp_path / "hint-repo"
    (hint_repo / "graphify-out").mkdir(parents=True)
    (hint_repo / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")

    hit = _run_command_string(bash_hint[0], _payload(
        tmp_path, "b1", {"tool_name": "Bash", "tool_input": {"command": "grep -rn foo ."}}),
        cwd=hint_repo)
    assert "graphify" in hit.stdout, \
        "the Bash search hint produced nothing for a grep command (dead interpreter?)"
    bash_context = json.loads(hit.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "py -3.12 -m graphify query" in bash_context
    assert "`graphify query" not in bash_context

    miss = _run_command_string(bash_hint[0], _payload(
        tmp_path, "b2", {"tool_name": "Bash", "tool_input": {"command": "python -m pytest -q"}}),
        cwd=hint_repo)
    assert not miss.stdout.strip(), "the Bash hint fired for a command that does no searching"

    hit2 = _run_command_string(read_hint[0], _payload(
        tmp_path, "r1", {"tool_name": "Read", "tool_input": {"file_path": "cisco_toolkit/model.py"}}),
        cwd=hint_repo)
    assert "graphify" in hit2.stdout, \
        "the Read/Glob hint produced nothing for a source file (dead interpreter?)"
    read_context = json.loads(hit2.stdout)["hookSpecificOutput"]["additionalContext"]
    for command in ("query", "explain", "path"):
        assert f"py -3.12 -m graphify {command}" in read_context
    assert "`graphify " not in read_context

    miss2 = _run_command_string(read_hint[0], _payload(
        tmp_path, "r2", {"tool_name": "Read", "tool_input": {"file_path": "deliverables/out.xlsx"}}),
        cwd=hint_repo)
    assert not miss2.stdout.strip(), "the Read hint fired for a non-source file"


# --------------------------------------------------------------------- graph-refresh.sh
# Fail-open MAINTENANCE (always exit 0), so exit status can never tell us whether it worked.
# The updater deliberately runs Python in isolated mode, so PYTHONPATH cannot be the fixture.
# Instead a pinned executable records the exact probe/update argv and returns controlled codes.


def _receipt_shim(tmp_path, name):
    shim = tmp_path / ("receipt-shim-" + name.replace(" ", "_").replace("/", "_") + ".py")
    shim.write_text(
        "import hashlib, json, os, sys\n"
        "from datetime import datetime, timezone\n"
        "mode, path, head, state = sys.argv[1:]\n"
        "root = os.path.realpath(os.getcwd())\n"
        "def graph():\n"
        "    p = os.path.join(os.path.dirname(path), 'graph.json')\n"
        "    data = open(p, 'rb').read()\n"
        "    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}\n"
        "def read():\n"
        "    try:\n"
        "        return json.load(open(path, encoding='utf-8'))\n"
        "    except Exception:\n"
        "        return None\n"
        "def payload(phase):\n"
        "    value = {'contract': 'test-refresh/1', 'guard': {'test_shim': True}, "
        "'head': head, 'phase': phase, 'root': root, 'state': state, "
        "'updated_at': datetime.now(timezone.utc).isoformat()}\n"
        "    if phase == 'complete': value['graph'] = graph()\n"
        "    return value\n"
        "if mode == '--receipt-status':\n"
        "    actual = read()\n"
        "    expected = payload('complete')\n"
        "    if actual: actual.pop('updated_at', None)\n"
        "    expected.pop('updated_at', None)\n"
        "    raise SystemExit(0 if state == 'clean' and actual == expected else 1)\n"
        "if mode == '--receipt-pending':\n"
        "    value = payload('pending')\n"
        "elif mode == '--receipt-complete':\n"
        "    current = read()\n"
        "    expected = payload('pending')\n"
        "    if current: current.pop('updated_at', None)\n"
        "    expected.pop('updated_at', None)\n"
        "    if current != expected: raise SystemExit(2)\n"
        "    value = payload('complete')\n"
        "else: raise SystemExit(2)\n"
        "tmp = path + '.tmp'\n"
        "with open(tmp, 'w', encoding='utf-8', newline='\\n') as f: json.dump(value, f)\n"
        "os.replace(tmp, path)\n",
        encoding="utf-8",
        newline="\n",
    )
    return shim


def _fake_graphify_python(tmp_path, name):
    receipt_shim = _receipt_shim(tmp_path, name)
    fake = tmp_path / ("fake-python-" + name.replace(" ", "_").replace("/", "_"))
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "{ printf 'CALL'; for arg in \"$@\"; do printf '\\t%s' \"$arg\"; done; "
        "printf '\\n'; } >> \"$GRAPHIFY_FAKE_LOG\"\n"
        "case \" $* \" in\n"
        "  *' --probe '*) exit \"${GRAPHIFY_FAKE_PROBE_RC:-0}\" ;;\n"
        f"  *' --receipt-'*) exec \"{Path(sys.executable).as_posix()}\" "
        f"\"{receipt_shim.as_posix()}\" \"${{@:4}}\" ;;\n"
        "  *' update . '*) [ -z \"${GRAPHIFY_FAKE_UPDATE_OUTPUT:-}\" ] || "
        "printf '%s\\n' \"$GRAPHIFY_FAKE_UPDATE_OUTPUT\"; exit \"${GRAPHIFY_FAKE_UPDATE_RC:-0}\" ;;\n"
        "  *) exit 97 ;;\n"
        "esac\n",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    return fake


def _graph_refresh_repo(tmp_path, name, *, with_graph=True):
    repo = _git_repo(tmp_path, name)
    (repo / "tools").mkdir()
    shutil.copy2(os.path.join(ROOT, "tools", "graphify_guarded.py"),
                 repo / "tools" / "graphify_guarded.py")
    (repo / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    subprocess.run([_GIT, "add", ".gitignore", "tools/graphify_guarded.py"],
                   cwd=str(repo), check=True)
    subprocess.run([_GIT, "commit", "-qm", "guard baseline"], cwd=str(repo), check=True)
    if with_graph:
        (repo / "graphify-out").mkdir()
        (repo / "graphify-out" / "graph.json").write_text(
            '{"sentinel":"unchanged"}\n', encoding="utf-8")
    return repo


def _complete_graph_refresh_receipt(repo, *, state="clean"):
    head = subprocess.run(
        [_GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    receipt = repo / "graphify-out" / ".guarded_refresh.json"
    shim = _receipt_shim(repo.parent, repo.name + "-preseed")
    for phase in ("--receipt-pending", "--receipt-complete"):
        completed = subprocess.run(
            [sys.executable, str(shim), phase, str(receipt), head, state],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
    return receipt


def _fake_only_path(tmp_path, fake):
    """Put controlled python/python3/py shims before any host interpreter."""
    fake_bin = tmp_path / (fake.name + "-bin")
    fake_bin.mkdir()
    for name in ("python", "python3", "py"):
        target = fake_bin / name
        shutil.copy2(fake, target)
        target.chmod(0o755)
    return str(fake_bin) + os.pathsep + os.environ.get("PATH", "")


def _graph_refresh_probe(tmp_path, filename, *, probe_rc=0, update_rc=7):
    slug = filename.replace(" ", "_").replace("/", "_")
    repo = _graph_refresh_repo(tmp_path, "gr_" + slug)
    content = '{"extends":"base.json"}\n' if filename.endswith((".json", ".jsonc")) \
        else "x = 1\n"
    (repo / filename).write_text(content, encoding="utf-8")
    fake = _fake_graphify_python(tmp_path, slug)
    log = tmp_path / ("graphify-argv-" + slug + ".log")
    (repo / "graphify-out" / ".graphify_python").write_text(
        fake.as_posix(), encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC=str(probe_rc),
        GRAPHIFY_FAKE_UPDATE_RC=str(update_rc),
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    )
    if probe_rc:
        env["PATH"] = _fake_only_path(tmp_path, fake)
    p = _run_hook("graph-refresh.sh", cwd=repo, env=env)
    assert p.returncode == 0, "graph-refresh must ALWAYS fail open; got rc=%d" % p.returncode
    calls = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            assert fields[0] == "CALL"
            calls.append(fields[1:])
    return p, calls, repo


def _is_guard_probe(call):
    return (
        len(call) == 4
        and call[:2] == ["-I", "-B"]
        and call[2].replace("\\", "/").endswith("/tools/graphify_guarded.py")
        and call[3] == "--probe"
    )


def _is_guard_update(call):
    return (
        len(call) == 5
        and call[:2] == ["-I", "-B"]
        and call[2].replace("\\", "/").endswith("/tools/graphify_guarded.py")
        and call[3:] == ["update", "."]
    )


def _is_any_update(call):
    return len(call) >= 2 and call[-2:] == ["update", "."]


@_needs_shell
def test_graph_refresh_detects_an_ordinary_changed_source_file(tmp_path):
    """Baseline — without this the 'quoted path' test below would pass on a hook that never
    detects anything at all."""
    p, calls, _ = _graph_refresh_probe(tmp_path, "mod.py")
    assert "guarded 'graphify update .' exited 7" in p.stderr
    assert any(_is_guard_probe(call) for call in calls)
    assert any(_is_guard_update(call) for call in calls)


@_needs_shell
def test_graph_refresh_detects_a_path_git_has_to_quote(tmp_path):
    """git wraps a porcelain path containing a space or a non-ASCII byte in quotes, so the line
    ends in `"` rather than `.py`. With a bare `\\.py$` the refresh silently skipped exactly those
    files and the graph rotted for them with no signal. Same defect class as verify-green.sh."""
    for name in ("my probe.py", "pr\u00fcbe.py"):
        p, calls, _ = _graph_refresh_probe(tmp_path, name)
        assert "guarded 'graphify update .' exited 7" in p.stderr and any(
            _is_guard_update(call) for call in calls), (
            "graph-refresh missed %r — git quotes that porcelain path, so the extension test "
            "must tolerate a trailing quote" % name)


@_needs_shell
def test_graph_refresh_detects_json_config_changes(tmp_path):
    """The guarded extractor fixes JSON semantics, so JSON config edits must reach it."""
    p, calls, _ = _graph_refresh_probe(tmp_path, "tsconfig.json")
    assert "guarded 'graphify update .' exited 7" in p.stderr
    assert any(_is_guard_update(call) for call in calls)


@_needs_shell
def test_graph_refresh_detects_document_changes(tmp_path):
    """Markdown is part of the graph corpus, so a documentation-only edit is not inert."""
    p, calls, _ = _graph_refresh_probe(tmp_path, "notes.md")
    assert "guarded 'graphify update .' exited 7" in p.stderr
    assert any(_is_guard_update(call) for call in calls)


@_needs_shell
def test_graph_refresh_detects_a_source_rename_to_an_unindexed_extension(tmp_path):
    """A rename-away must remove the old source nodes even though the new suffix is not indexed."""
    repo = _graph_refresh_repo(tmp_path, "gr_rename_away")
    (repo / "old.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([_GIT, "add", "old.py"], cwd=str(repo), check=True)
    subprocess.run([_GIT, "commit", "-qm", "tracked source"], cwd=str(repo), check=True)
    subprocess.run([_GIT, "mv", "old.py", "old.unindexed"], cwd=str(repo), check=True)

    fake = _fake_graphify_python(tmp_path, "rename_away")
    log = tmp_path / "graphify-argv-rename-away.log"
    (repo / "graphify-out" / ".graphify_python").write_text(
        fake.as_posix(), encoding="utf-8")
    p = _run_hook("graph-refresh.sh", cwd=repo, env=_env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="7",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    ))
    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert p.returncode == 0 and "guarded 'graphify update .' exited 7" in p.stderr
    assert any(_is_guard_update(call) for call in calls)


@_needs_shell
def test_graph_refresh_probe_failure_prevents_graph_mutation_but_allows_stop(tmp_path):
    """A wrong version/hash is loud and cannot fall through to the mutating command."""
    p, calls, repo = _graph_refresh_probe(tmp_path, "mod.py", probe_rc=19, update_rc=0)
    assert p.returncode == 0
    assert "guard probe failed" in p.stderr
    assert "graph not mutated" in p.stderr
    assert "0.9.47" in p.stderr
    assert calls and all(not _is_any_update(call) for call in calls)
    assert (repo / "graphify-out" / "graph.json").read_text(encoding="utf-8") == \
        '{"sentinel":"unchanged"}\n'


@_needs_shell
def test_graph_refresh_git_status_failure_is_loud_and_does_not_mutate(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_status_failure")
    # rev-parse still resolves the worktree, but status cannot read an index
    # path that is a directory. This avoids PATH/MSYS executable rewriting.
    index = repo / ".git" / "index"
    index.unlink()
    index.mkdir()

    p = _run_hook("graph-refresh.sh", cwd=repo)

    assert p.returncode == 0
    assert "git status failed" in p.stderr
    assert "graph not mutated" in p.stderr
    assert (repo / "graphify-out" / "graph.json").read_text(encoding="utf-8") == \
        '{"sentinel":"unchanged"}\n'


@_needs_shell
def test_graph_refresh_success_is_quiet_and_uses_guarded_update(tmp_path):
    p, calls, _ = _graph_refresh_probe(tmp_path, "mod.py", update_rc=0)
    assert not p.stderr.strip()
    assert sum(_is_guard_probe(call) for call in calls) == 1
    updates = [call for call in calls if _is_any_update(call)]
    assert len(updates) == 1 and _is_guard_update(updates[0])


@_needs_shell
def test_graph_refresh_runs_for_clean_commit_drift_and_finalizes_current_receipt(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_clean_commit")
    _complete_graph_refresh_receipt(repo)
    (repo / "notes.md").write_text("# Structurally new\n", encoding="utf-8")
    subprocess.run([_GIT, "add", "notes.md"], cwd=repo, check=True)
    subprocess.run([_GIT, "commit", "-qm", "clean drift"], cwd=repo, check=True)

    fake = _fake_graphify_python(tmp_path, "clean_commit")
    log = tmp_path / "graphify-argv-clean-commit.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="0",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    )

    p = _run_hook("graph-refresh.sh", cwd=repo, env=env)

    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert p.returncode == 0 and not p.stderr.strip()
    assert sum(_is_any_update(call) for call in calls) == 1
    receipt = json.loads(
        (repo / "graphify-out" / ".guarded_refresh.json").read_text(encoding="utf-8")
    )
    head = subprocess.run(
        [_GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert receipt["phase"] == "complete"
    assert receipt["state"] == "clean" and receipt["head"] == head


@_needs_shell
def test_graph_refresh_runs_when_ignored_graph_bytes_no_longer_match_receipt(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_graph_replaced")
    _complete_graph_refresh_receipt(repo)
    (repo / "graphify-out" / "graph.json").write_text(
        '{"replaced":true}\n', encoding="utf-8"
    )
    fake = _fake_graphify_python(tmp_path, "graph_replaced")
    log = tmp_path / "graphify-argv-graph-replaced.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="0",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    )

    p = _run_hook("graph-refresh.sh", cwd=repo, env=env)

    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert p.returncode == 0 and not p.stderr.strip()
    assert sum(_is_any_update(call) for call in calls) == 1


@_needs_shell
def test_graph_refresh_reconciles_dirty_refresh_then_clean_revert_at_same_head(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_dirty_revert")
    (repo / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run([_GIT, "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run([_GIT, "commit", "-qm", "tracked baseline"], cwd=repo, check=True)
    _complete_graph_refresh_receipt(repo)
    (repo / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    fake = _fake_graphify_python(tmp_path, "dirty_revert")
    log = tmp_path / "graphify-argv-dirty-revert.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="0",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    )
    first = _run_hook("graph-refresh.sh", cwd=repo, env=env)
    assert first.returncode == 0 and not first.stderr.strip()
    dirty_receipt = json.loads(
        (repo / "graphify-out" / ".guarded_refresh.json").read_text(encoding="utf-8")
    )
    assert dirty_receipt["phase"] == "complete" and dirty_receipt["state"] == "dirty"

    subprocess.run([_GIT, "restore", "tracked.py"], cwd=repo, check=True)
    log.unlink()
    second = _run_hook("graph-refresh.sh", cwd=repo, env=env)
    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert second.returncode == 0 and not second.stderr.strip()
    assert sum(_is_any_update(call) for call in calls) == 1
    clean_receipt = json.loads(
        (repo / "graphify-out" / ".guarded_refresh.json").read_text(encoding="utf-8")
    )
    assert clean_receipt["phase"] == "complete" and clean_receipt["state"] == "clean"


@_needs_shell
def test_graph_refresh_ignores_ambient_git_checkout_redirection(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_git_env_target")
    other = _git_repo(tmp_path, "gr_git_env_other")
    (repo / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    fake = _fake_graphify_python(tmp_path, "git_env")
    log = tmp_path / "graphify-argv-git-env.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="7",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
        GIT_DIR=str(other / ".git"),
        GIT_WORK_TREE=str(other),
    )

    p = _run_hook("graph-refresh.sh", cwd=repo, env=env)

    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert p.returncode == 0 and "guarded 'graphify update .' exited 7" in p.stderr
    assert any(_is_guard_update(call) for call in calls)


def test_graph_refresh_has_no_unbounded_update_fallback():
    text = _read(".claude", "hooks", "graph-refresh.sh")
    assert 'if [ -z "$TIMEOUT" ]; then' in text
    assert "single-worker refresh cannot be bounded" in text
    assert '"$TIMEOUT" --kill-after=5s 180s "$PY" -I -B "$RUNNER" update .' in text
    assert '"$TIMEOUT" --kill-after=2s 15s "$GIT" ' in text
    assert "GIT=$(type -P git" in text
    assert 'case "${_name^^}" in GIT_*)' in text
    assert '"$TIMEOUT" 180 "$PY"' not in text
    assert '\n  "$PY" -I -B "$RUNNER" update .' not in text
    refresh = next(
        hook
        for entry in _settings()["hooks"]["Stop"]
        for hook in entry["hooks"]
        if "graph-refresh.sh" in hook.get("command", "")
    )
    assert refresh["timeout"] >= 600


@_needs_shell
def test_graph_refresh_failure_includes_a_bounded_producer_diagnostic(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_diagnostic")
    (repo / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    fake = _fake_graphify_python(tmp_path, "diagnostic")
    log = tmp_path / "graphify-argv-diagnostic.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    sentinel = "G018: producer lock deliberately held"
    p = _run_hook("graph-refresh.sh", cwd=repo, env=_env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="2",
        GRAPHIFY_FAKE_UPDATE_OUTPUT=sentinel,
    ))
    assert p.returncode == 0
    assert "exited 2" in p.stderr and sentinel in p.stderr
    assert "bounded producer log tail" in p.stderr


@_needs_shell
def test_graph_refresh_serializes_and_recovers_an_expired_transaction_lock(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_transaction_lock")
    (repo / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    fake = _fake_graphify_python(tmp_path, "transaction_lock")
    call_log = tmp_path / "graphify-argv-transaction-lock.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    lock = repo / "graphify-out" / ".guarded_refresh.lock"
    lock.mkdir()
    (lock / "owner").write_text("0 malformed\n", encoding="utf-8")
    env = _env_with(
        GRAPHIFY_FAKE_LOG=str(call_log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="7",
    )

    current = _run_hook("graph-refresh.sh", cwd=repo, env=env)
    calls = [line.split("\t")[1:] for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert "another guarded refresh owns" in current.stderr
    assert all(not _is_any_update(call) for call in calls)

    old = 1_000_000_000
    os.utime(lock, (old, old))
    call_log.unlink()
    recovered = _run_hook("graph-refresh.sh", cwd=repo, env=env)
    calls = [line.split("\t")[1:] for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert "guarded 'graphify update .' exited 7" in recovered.stderr
    assert any(_is_guard_update(call) for call in calls)


@_needs_shell
def test_graph_refresh_stale_lock_recovery_never_dereferences_a_link(tmp_path):
    repo = _graph_refresh_repo(tmp_path, "gr_linked_transaction_lock")
    (repo / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    fake = _fake_graphify_python(tmp_path, "linked_transaction_lock")
    call_log = tmp_path / "graphify-argv-linked-transaction-lock.log"
    (repo / "graphify-out" / ".graphify_python").write_text(fake.as_posix(), encoding="utf-8")
    outside = tmp_path / "external-lock-target"
    outside.mkdir()
    sentinel = outside / "owner"
    sentinel.write_text("must survive\n", encoding="utf-8")
    lock = repo / "graphify-out" / ".guarded_refresh.lock"
    try:
        lock.symlink_to(outside, target_is_directory=True)
        os.utime(lock, (1_000_000_000, 1_000_000_000), follow_symlinks=False)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlink timestamps are unavailable")

    p = _run_hook("graph-refresh.sh", cwd=repo, env=_env_with(
        GRAPHIFY_FAKE_LOG=str(call_log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_FAKE_UPDATE_RC="7",
    ))
    assert p.returncode == 0
    if not list((repo / "graphify-out").glob(".guarded_refresh.lock.stale.*")):
        pytest.skip("Git Bash stat did not expose the symlink object's stale timestamp")
    assert sentinel.read_text(encoding="utf-8") == "must survive\n"


@_needs_shell
def test_graph_refresh_is_inert_without_a_graph_or_with_a_current_clean_receipt(tmp_path):
    """No graph and matching clean endpoint bookkeeping are the two deliberate no-op states."""
    repo = _graph_refresh_repo(tmp_path, "gr_nograph", with_graph=False)
    (repo / "mod.py").write_text("x = 1\n", encoding="utf-8")
    p = _run_hook("graph-refresh.sh", cwd=repo)
    assert p.returncode == 0 and "graph-refresh:" not in p.stderr, \
        "ran the updater with no graphify-out/graph.json to update"

    repo2 = _graph_refresh_repo(tmp_path, "gr_clean")
    receipt = _complete_graph_refresh_receipt(repo2)
    receipt_before = receipt.read_bytes()
    fake = _fake_graphify_python(tmp_path, "current-clean")
    log = tmp_path / "graphify-argv-current-clean.log"
    (repo2 / "graphify-out" / ".graphify_python").write_text(
        fake.as_posix(), encoding="utf-8"
    )
    p2 = _run_hook("graph-refresh.sh", cwd=repo2, env=_env_with(
        GRAPHIFY_FAKE_LOG=str(log),
        GRAPHIFY_FAKE_PROBE_RC="0",
        GRAPHIFY_RECEIPT_PYTHON=sys.executable,
    ))
    calls = [line.split("\t")[1:] for line in log.read_text(encoding="utf-8").splitlines()]
    assert p2.returncode == 0 and "graph-refresh:" not in p2.stderr, \
        "a current clean receipt triggered a redundant graph rebuild"
    assert sum(_is_guard_probe(call) for call in calls) == 1
    assert all(not _is_any_update(call) for call in calls)
    assert receipt.read_bytes() == receipt_before


# --------------------------------------------------------------------- scorecard-append.sh
# The QA scorecard is the project's proposer!=verifier evidence trail. `--hook` is total by
# contract (cisco_toolkit/scorecard.py :: main returns 0 and swallows its own exceptions), so a
# non-zero status means the RECORDER is gone. That must stay fail-open, and must be audible.

@_needs_shell
def test_scorecard_hook_is_loud_when_the_recorder_is_dead(tmp_path):
    """Verified failure mode: with a broken recorder the hook emitted zero bytes and exited 0, so
    the scorecard just stopped growing and the morning briefing kept reporting 'no entries' —
    which reads as 'no QA ran', not 'the recorder is broken'."""
    payload = _payload(tmp_path, "sc", {"session_id": "x", "transcript_path": "nope"})
    # Run from a throwaway repo so the real package in the checkout's cwd (which `-m` puts at
    # sys.path[0], ahead of PYTHONPATH) cannot shadow the shim, and point PYTHONPATH at a
    # cisco_toolkit whose scorecard exits 9 so any installed copy loses too.
    repo = _git_repo(tmp_path, "sc_repo")
    env = _env_with(PYTHONPATH=_pythonpath_shim(tmp_path, "cisco_toolkit", "scorecard", 9))
    p = _run_hook("scorecard-append.sh", payload, cwd=repo, env=env)
    assert p.returncode == 0, "the scorecard hook must never block a turn (rc=%d)" % p.returncode
    assert "scorecard-append" in p.stderr and "9" in p.stderr, (
        "a DEAD scorecard recorder produced no warning at all — stderr=%r" % p.stderr)


@_needs_shell
def test_scorecard_hook_stays_quiet_on_an_ordinary_non_qa_stop(tmp_path):
    """The counterweight: it fires on EVERY subagent stop, so a healthy no-op must say nothing.
    Otherwise the warning above is noise and gets ignored."""
    payload = _payload(tmp_path, "sc2", {"session_id": "x", "transcript_path": "nope"})
    p = _run_hook("scorecard-append.sh", payload)
    assert p.returncode == 0
    assert not p.stderr.strip(), \
        "a healthy non-QA subagent stop emitted a warning: %r" % p.stderr[-200:]


# --------------------------------------------------------------------- vault-guard.sh
# The Write|Edit|NotebookEdit lane of ADR 0001. This one must FAIL CLOSED on the path, and fail
# OPEN on everything else (a hook bug must never wedge a turn). Paths live in this file as python
# literals and reach the hook only through a json FILE — never through argv, which the MSYS
# converter rewrites mid-flight.

_VAULT_BLOCK = {
    "canonical windows spelling": ("file_path", "C:\\Vaults\\brain\\wiki\\x.md"),
    "forward slashes": ("file_path", "C:/Vaults/brain/wiki/x.md"),
    "msys drive spelling": ("file_path", "/c/Vaults/brain/wiki/x.md"),
    "notebook_path key": ("notebook_path", "C:/Vaults/brain/nb.ipynb"),
    "uppercase": ("file_path", "C:/VAULTS/BRAIN/X.MD"),
    "vault root itself": ("file_path", "C:/Vaults/brain"),
    # the four spellings that used to slip through
    "extended-length UNC prefix": ("file_path", "\\\\?\\C:\\Vaults\\brain\\x.md"),
    "device-path prefix": ("file_path", "\\\\.\\C:\\Vaults\\brain\\x.md"),
    "double-slash drive": ("file_path", "//c/Vaults/brain/x.md"),
    "cygdrive spelling": ("file_path", "/cygdrive/c/Vaults/brain/x.md"),
    "reached through ..": ("file_path",
                           "C:/Users/x/Desktop/Enhancements/../../../../Vaults/brain/x.md"),
    "dot segments": ("file_path", "C:/Vaults/./brain/./wiki/x.md"),
}

_VAULT_PASS = {
    "repo-relative doc": ("file_path", "docs/log.md"),
    "repo absolute path": ("file_path", "C:/Users/x/Desktop/Enhancements/cisco_toolkit/model.py"),
    "another drive": ("file_path", "D:/Vaults/brain/x.md"),
    "another drive, cygdrive": ("file_path", "/cygdrive/d/Vaults/brain/x.md"),
    "another drive, msys": ("file_path", "/d/work/notes.md"),
    "unrelated C: path": ("file_path", "C:/Users/x/Documents/notes.md"),
}


@_needs_shell
@pytest.mark.parametrize("label", sorted(_VAULT_BLOCK))
def test_vault_guard_blocks_every_spelling_of_the_vault(tmp_path, label):
    key, path = _VAULT_BLOCK[label]
    p = _run_hook("vault-guard.sh", _payload(tmp_path, "vg", {"tool_name": "Write",
                                                              "tool_input": {key: path}}))
    assert p.returncode == 2, (
        "ADR 0001: a write to the vault spelled %r (%s) was ALLOWED (rc=%d)" % (path, label,
                                                                               p.returncode))
    assert "ADR 0001" in p.stderr, "blocked without citing the rule"


@_needs_shell
@pytest.mark.parametrize("label", sorted(_VAULT_PASS))
def test_vault_guard_passes_everything_outside_the_vault(tmp_path, label):
    key, path = _VAULT_PASS[label]
    p = _run_hook("vault-guard.sh", _payload(tmp_path, "vg", {"tool_name": "Write",
                                                              "tool_input": {key: path}}))
    assert p.returncode == 0, (
        "an ordinary write to %r (%s) was blocked (rc=%d) — the guard over-blocks and would wedge "
        "normal work" % (path, label, p.returncode))


@_needs_shell
@pytest.mark.parametrize("body", ["", "not json at all", "{}", '{"tool_input":{}}',
                                  '{"tool_input":{"file_path":null}}'])
def test_vault_guard_fails_open_on_a_payload_it_cannot_read(tmp_path, body):
    """A hook bug or a payload-shape change must never wedge a turn — the documented trade."""
    p = tmp_path / "raw.json"
    p.write_text(body, encoding="utf-8")
    r = _run_hook("vault-guard.sh", str(p))
    assert r.returncode == 0, "unreadable payload %r blocked the tool call (rc=%d)" % (
        body, r.returncode)


# --------------------------------------------------------------------- the workflows
# Static, but about properties no run can demonstrate to us offline.

def test_publish_job_keeps_contents_read():
    """A job-level `permissions:` block REPLACES the workflow-level one — everything unlisted
    becomes `none`. Listing only `id-token: write` therefore removed the `contents: read` that
    actions/checkout needs, and the publish job could die at step one."""
    pub = _read(".github", "workflows", "publish.yml")
    job = pub.split("pypi-publish:", 1)[1]
    block = job.split("permissions:", 1)[1].split("steps:", 1)[0]
    # Read the SCOPE KEYS, not the prose: the rationale comment directly above them names
    # `contents: read`, so a substring search over the raw block passes on a job that lost it.
    # (Caught by mutation-testing this very assertion.)
    scopes = {ln.split("#", 1)[0].strip() for ln in block.splitlines()
              if ln.strip() and not ln.strip().startswith("#")}
    scopes.discard("")
    assert "id-token: write" in scopes, "trusted publishing needs id-token: write"
    assert "contents: read" in scopes, (
        "job-level permissions dropped contents: read — a job-level block replaces the "
        "workflow-level one, so actions/checkout is left with no token scope. Got: %s" % scopes)


def test_webapp_ci_always_reports_pr_jobs_and_fails_closed_on_scope_errors():
    """A required check cannot live behind a top-level PR path filter.

    GitHub leaves every check from a path-skipped workflow Pending, which would deadlock an
    unrelated PR as soon as any webapp job becomes required. The workflow must start for every
    PR, classify paths once, and skip jobs only at job level. A classifier failure must run and
    fail each gated job rather than turning it into a successful skip.
    """
    wf = _read(".github", "workflows", "webapp-ci.yml")
    triggers = wf.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "pull_request:" in triggers
    assert "types: [opened, synchronize, reopened, edited]" in triggers
    lists = [ln for ln in triggers.splitlines() if ln.strip().startswith("paths:")]
    assert len(lists) == 1, "only push may retain a top-level path filter: %s" % lists

    scope = wf.split("\n  scope:", 1)[1].split("\n  backend:", 1)[0]
    assert "fetch-depth: 0" in scope
    assert "classify_webapp_ci_scope.py" in scope
    assert "steps.classify.outputs.relevant" in scope
    assert "Validate the classifier contract" in scope
    assert "true|false" in scope

    job_sections = {
        "backend": wf.split("\n  backend:", 1)[1].split("\n  frontend:", 1)[0],
        "frontend": wf.split("\n  frontend:", 1)[1].split("\n  e2e:", 1)[0],
        "e2e": wf.split("\n  e2e:", 1)[1].split("\n  visual:", 1)[0],
        "visual": wf.split("\n  visual:", 1)[1],
    }
    required_condition = (
        "always() && (needs.scope.result != 'success' || "
        "needs.scope.outputs.relevant == 'true')"
    )
    for name, job in job_sections.items():
        assert "needs: scope" in job, "%s can run without scope classification" % name
        assert required_condition in job, "%s does not fail closed on scope errors" % name
        assert "Fail closed when scope classification did not succeed" in job
        assert "if: ${{ needs.scope.result != 'success' }}" in job


def test_webapp_visual_gate_has_one_explicit_hosted_pixel_oracle():
    """System fonts make a broad ``Windows`` label an ambiguous pixel contract.

    Pull-request code must compare only on the explicit hosted Server 2025 image; the shared
    self-hosted dev box remains a behavioral-E2E lane and cannot consume the hosted raster set.
    Canonical refresh is an explicit artifact-only dispatch, never an automatic commit.
    """
    webapp = _read(".github", "workflows", "webapp-ci.yml")
    visual = webapp.split("\n  visual:", 1)[1]
    assert "runs-on: windows-2025" in visual
    assert visual.count("\n        run: npm run test:visual\n") == 2
    assert 'VISUAL_ORACLE_CAPTURE: "1"' in visual
    assert visual.count("\n        run: npm run test:visual:update\n") == 1
    assert "actions/upload-artifact@" in visual
    assert "contents: write" not in webapp
    candidate_upload = visual.split(
        "\n      - name: Upload candidate visual baselines", 1
    )[1].split("\n      - name:", 1)[0]
    assert "success()" in candidate_upload
    assert "always()" not in candidate_upload
    provenance = visual.split("\n      - name: Record visual-oracle versions", 1)[1].split(
        "\n      - name:", 1
    )[0]
    assert "steps.install.outcome == 'success'" in provenance
    assert ".\\node_modules\\.bin\\playwright.cmd --version" in provenance
    assert "npx playwright --version" not in provenance

    visual_config = _read("webapp", "frontend", "playwright.visual.config.ts")
    assert 'VISUAL_BASELINE_ID = "windows-2025-x64"' in _read(
        "webapp", "frontend", "visual-e2e", "oracle.ts"
    )
    for guard in ("GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_ARCH"):
        assert guard in visual_config
    assert "test-results/visual-candidates" in visual_config
    assert "threshold: 0.02" in visual_config

    visual_spec = _read(
        "webapp", "frontend", "visual-e2e", "design-cards.visual.spec.ts"
    )
    assert "threshold: 0.2, maxDiffPixels: TOPOLOGY_RASTER_BUDGET" in visual_spec

    self_hosted = _read(".github", "workflows", "main-selfhosted.yml")
    assert "test:visual" not in self_hosted, (
        "the unversioned self-hosted Windows machine cannot share hosted pixel baselines"
    )


def test_no_ci_step_swallows_a_failure_outside_the_documented_report():
    """`continue-on-error` and `|| true` turn a red step green. Exactly one is allowed here: the
    documented non-gating mypy full report. Anything else is a gate that stopped gating."""
    for wf_name in ("ci.yml", "webapp-ci.yml"):
        wf = _read(".github", "workflows", wf_name)
        # Count the YAML KEY, not the word — the rationale comment mentions it by name.
        keys = [ln for ln in wf.splitlines()
                if ln.strip().lstrip("- ").startswith("continue-on-error:")]
        assert len(keys) == (1 if wf_name == "ci.yml" else 0), (
            "%s has %d continue-on-error step(s); only the documented non-gating mypy report may "
            "swallow a failure" % (wf_name, len(keys)))
        # Comment lines are prose ABOUT the rule (ci.yml explains why `|| true` was removed).
        body = "\n".join(ln for ln in wf.splitlines() if not ln.strip().startswith("#"))
        assert "|| true" not in body, \
            "%s swallows a step failure with `|| true` (and it is a PowerShell parse error on " \
            "the self-hosted Windows fleet)" % wf_name
