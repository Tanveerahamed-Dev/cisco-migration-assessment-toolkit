"""Doctrine-as-tests for the verification gates themselves (Plan A / Move-0.2).

The class this pins: an asset EXISTS but silently sits outside the gate — webapp/tests
lived outside the default suite + Stop hook for months, and the ~2700-line entry module
sat outside the coverage measurement. "Suite green" is only meaningful if what should be
gated actually is; these tests fail the moment a gate un-wires."""
import configparser
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BASH = shutil.which("bash")
_GIT = shutil.which("git")
_HOOK = os.path.join(ROOT, ".claude", "hooks", "verify-green.sh")
#: Per-test, NOT a module-level pytestmark: a bash-less box must still get the four
#: static gate assertions below, which need no shell.
_needs_shell = pytest.mark.skipif(not (_BASH and _GIT and os.path.isfile(_HOOK)),
                                  reason="bash / git / verify-green.sh unavailable")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_default_suite_gates_webapp_tests():
    """pytest.ini testpaths must carry BOTH roots — the bare `python -m pytest` that the
    developer, CI and the verify-green Stop hook all run must include webapp/tests."""
    ini = configparser.ConfigParser()
    ini.read(os.path.join(ROOT, "pytest.ini"))
    paths = ini["pytest"]["testpaths"].split()
    assert "tests" in paths, f"engine tests missing from testpaths: {paths}"
    assert "webapp/tests" in paths, f"webapp/tests dropped from the default gate: {paths}"


def test_webapp_suite_skips_cleanly_without_web_deps():
    """Engine-only environments (the CI test matrix installs no fastapi) must SKIP the
    webapp directory at collection, never ERROR at import — that guard lives in
    webapp/tests/conftest.py and must stay."""
    guard = _read("webapp", "tests", "conftest.py")
    assert "find_spec" in guard and "collect_ignore_glob" in guard, \
        "webapp/tests/conftest.py lost its collection guard (engine-only CI would ERROR)"


def test_webapp_un_collection_is_announced_not_silent(monkeypatch):
    """...and when it DOES skip, it must say so. `collect_ignore_glob` emits no skip report and
    no reason line, and pytest.ini sets `-q`, so a run that silently dropped ~20 webapp test
    files — the Atlas redaction suite, security hardening, unplug safety — looked exactly like a
    full green one, including to the verify-green Stop hook. Asserted against the guard's own
    state rather than its source text, so the assertion cannot rot into a grep.

    BOTH branches are DRIVEN, not observed. This test used to read whichever branch the box it
    ran on happened to take — and every box that matters day to day (the developer machine, the
    verify-green Stop hook, webapp-ci) has the web deps installed, so it only ever asserted
    `announced is None` and the announcement itself was pinned by nothing. Proven vacuous by
    mutation (2026-07-28): deleting the entire announcement from
    `webapp/tests/conftest.py::pytest_report_collectionfinish` — leaving a bare `return None` —
    left this test GREEN. It is the engine-only runner, where nobody is watching, that needs the
    banner, so the missing-deps state is now forced here instead of waited for."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        "_webapp_conftest_probe", os.path.join(ROOT, "webapp", "tests", "conftest.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "MISSING_WEB_DEPS"), \
        "the guard no longer publishes which deps are missing — un-collection is silent again"
    assert hasattr(mod, "pytest_report_collectionfinish"), \
        "the guard no longer announces the un-collection to the terminal reporter"

    # The branch that matters, forced: deps missing -> the run must SAY the suites did not run,
    # and must name which dependency caused it (a bare "something was skipped" is not actionable).
    monkeypatch.setattr(mod, "MISSING_WEB_DEPS", ("fastapi", "httpx"))
    announced = mod.pytest_report_collectionfinish(None)
    assert announced, "web deps missing and the run says NOTHING about the dropped suites"
    assert "NOT COLLECTED" in announced, f"the un-collection is not stated plainly: {announced!r}"
    assert "fastapi" in announced, f"the announcement does not name the missing dep: {announced!r}"

    # ...and the quiet branch stays quiet, so this cannot be greened by an always-on banner that
    # operators would learn to ignore.
    monkeypatch.setattr(mod, "MISSING_WEB_DEPS", ())
    assert mod.pytest_report_collectionfinish(None) is None, \
        "nothing was dropped, so nothing should be announced"

    # ...and on THIS box the guard's real state and the collection decision must agree.
    monkeypatch.undo()
    assert bool(mod.MISSING_WEB_DEPS) == hasattr(mod, "collect_ignore_glob"), (
        f"MISSING_WEB_DEPS={mod.MISSING_WEB_DEPS!r} disagrees with whether the directory is "
        f"actually un-collected — the announcement would describe the wrong run")


def test_coverage_measures_the_entry_module():
    """The entry module (COLLECT_PARSE_V3_23_0) is exercised in-process by
    tests/test_pipeline_inprocess.py — it must be MEASURED. The pinned mechanism:
    [tool.coverage.run] source_pkgs (an importable-name list that pytest-cov's
    --cov=<pkg> flag does NOT override, so the CI flag and the config compose).
    Verified hazard: the --cov=<file>.py PATH form hard-crashes pytest-cov on this
    stack (rc=120, no output) — never reintroduce it."""
    pyproject = _read("pyproject.toml")
    run_section = pyproject.split("[tool.coverage.run]", 1)[1].split("[tool.", 1)[0]
    assert "COLLECT_PARSE_V3_23_0" in run_section and "source_pkgs" in run_section, \
        "entry module dropped from [tool.coverage.run] source_pkgs"
    assert "cisco_toolkit" in run_section
    ci = _read(".github", "workflows", "ci.yml")
    assert "--cov=cisco_toolkit" in ci
    assert "--cov=COLLECT_PARSE_V3_23_0" not in ci, \
        "the module-name/path --cov forms are broken on this stack — use source_pkgs"


def test_stop_hook_runs_the_default_suite():
    """verify-green.sh must invoke pytest WITHOUT a positional path (a hard-coded
    `pytest tests` would silently un-gate webapp/tests from the Stop hook)."""
    hook = _read(".claude", "hooks", "verify-green.sh")
    assert "-m pytest" in hook, "Stop hook no longer runs pytest at all?"
    assert "pytest tests" not in hook and "pytest -q tests" not in hook, \
        "Stop hook pins a positional test path — it must run the default testpaths"


# --------------------------------------------------------------- the hook, EXECUTED
# Everything above reads the hook's TEXT. That is not the same as knowing it works, and
# this is the gate every other test's meaning rests on: if verify-green.sh stops
# blocking, "suite green" stops being a claim about the code. Text assertions cannot see
# the ways it actually breaks -- `rc=$?` moved behind a pipe (so rc reads the pipe's last
# command and a RED suite reports 0), `exit 2` becoming `exit 0`, the `-eq 0` test
# inverted, or the change detector missing a file. All four leave "-m pytest" present and
# "pytest tests" absent. So: run it, against a suite whose colour we chose.

_GREEN_TEST = "def test_ok():\n    assert True\n"
_RED_TEST = "def test_bad():\n    assert False, 'deliberately red'\n"


def _hook_repo(tmp_path, filename, body):
    """A throwaway git repo holding ONE python test file -- enough for the hook to see a
    changed .py AND to have a suite to run."""
    subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / filename).write_text(body, encoding="utf-8")
    return tmp_path


def _run_hook(repo):
    return subprocess.run([_BASH, _HOOK], cwd=str(repo), capture_output=True, text=True,
                          timeout=300)


@_needs_shell
def test_stop_hook_BLOCKS_on_a_red_suite(tmp_path):
    """The whole point of the hook. Exit 2 is what blocks the turn."""
    p = _run_hook(_hook_repo(tmp_path, "test_probe.py", _RED_TEST))
    assert p.returncode == 2, (
        f"a failing suite did NOT block the turn (rc={p.returncode}). "
        f"stdout={p.stdout!r} stderr={p.stderr[-400:]!r}")
    assert "BLOCKED" in p.stderr, "blocked without telling the caller why"


@_needs_shell
def test_stop_hook_ALLOWS_a_green_suite(tmp_path):
    """The other half: a green suite must not trap the user in a loop."""
    p = _run_hook(_hook_repo(tmp_path, "test_probe.py", _GREEN_TEST))
    assert p.returncode == 0, (
        f"a passing suite still blocked (rc={p.returncode}). stderr={p.stderr[-400:]!r}")


@_needs_shell
def test_stop_hook_is_inert_when_no_python_changed(tmp_path):
    """Scope: the hook gates *.py only. A docs-only turn must pass straight through."""
    repo = _hook_repo(tmp_path, "notes.txt", "no python here\n")
    assert _run_hook(repo).returncode == 0, "a non-Python change was gated"


def _branch_repo(tmp_path, body):
    """A repo with a real base branch and one commit on a feature branch — the shape the gate
    actually runs in. A repo with no `main` and no upstream has nothing to diff against, which is
    exactly how an earlier version of this test passed while proving nothing."""
    subprocess.run([_GIT, "init", "-q", "-b", "main", "."], cwd=tmp_path, check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run([_GIT, "config", k, v], cwd=tmp_path, check=True)
    # The BASE must differ from `body`, or `git commit` on the feature branch finds nothing to
    # commit and the branch carries no .py change at all — which is how the first cut of this test
    # failed: it was asserting against a repo whose feature branch was identical to its base.
    (tmp_path / "test_base.py").write_text(_GREEN_TEST, encoding="utf-8")
    # Every real Python repo ignores this; without it the hook's own pytest run creates
    # __pycache__/ and moves `git status` for a reason that has nothing to do with the code under
    # test — which the porcelain precondition below correctly refused to accept.
    (tmp_path / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    subprocess.run([_GIT, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([_GIT, "commit", "-qm", "base"], cwd=tmp_path, check=True)
    subprocess.run([_GIT, "switch", "-qc", "feature"], cwd=tmp_path, check=True)
    (tmp_path / "test_probe.py").write_text(body, encoding="utf-8")
    subprocess.run([_GIT, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([_GIT, "commit", "-qm", "work"], cwd=tmp_path, check=True)
    committed = subprocess.run([_GIT, "diff", "--name-only", "main...HEAD"], cwd=tmp_path,
                               capture_output=True, text=True).stdout
    assert "test_probe.py" in committed, (
        f"precondition: the feature branch must carry a COMMITTED .py change vs main, got {committed!r}")
    return tmp_path


@_needs_shell
def test_stop_hook_still_gates_after_the_change_is_COMMITTED(tmp_path):
    """The gate read `git status --porcelain` — the WORKING TREE only — so it went completely inert
    the moment a turn's Python changes were committed, which is the ordinary end-of-work action in
    this repo rather than an edge case. Reproduced before the fix: the identical red suite blocked
    at exit 2 while uncommitted and allowed at exit 0 once committed. CLAUDE.md advertises this hook
    as blocking "after any .py change"."""
    p = _run_hook(_branch_repo(tmp_path, _RED_TEST))
    assert p.returncode == 2, (
        f"a red suite committed to a feature branch did NOT block (rc={p.returncode}) — the gate is "
        f"inert for committed work. stderr={p.stderr[-300:]!r}")


@_needs_shell
def test_stop_hook_skips_the_rerun_when_nothing_changed_since_green(tmp_path):
    """...and the reason gating committed work is affordable. Without this the full ~2,000-test
    suite would re-run on EVERY turn of any branch carrying a .py commit, including docs-only and
    question-only turns. The state key covers HEAD, the porcelain status, the tracked diff CONTENT
    and every untracked file, so it moves whenever anything the suite would see moves.

    Honest scope: this pins that the marker is WRITTEN and that a content-only edit INVALIDATES it.
    It does NOT pin that the cache is actually consulted — deleting the skip leaves the hook
    correct, just slower, so both paths return 0 on green and no exit code can tell them apart.
    Verified by mutation: disabling the skip does not turn this test red, and that is the right
    answer rather than a reason to add a flaky timing assertion."""
    repo = _branch_repo(tmp_path, _GREEN_TEST)

    # Leave the file MODIFIED-but-green before the first run, so that the later red edit changes
    # only its CONTENT and not `git status --porcelain`. Without this the file goes clean->modified
    # and the porcelain text moves too, so a key built from the status alone would still change and
    # the assertion below would pass against a key that never looked at content. (Caught by
    # mutation: removing `git diff HEAD` from the key left this test green.)
    (repo / "test_probe.py").write_text(_GREEN_TEST + "\n# edit\n", encoding="utf-8")
    porcelain_before = subprocess.run([_GIT, "status", "--porcelain"], cwd=str(repo),
                                      capture_output=True, text=True).stdout

    assert _run_hook(repo).returncode == 0, "precondition: a green branch must be allowed"
    marker = repo / ".git" / "verify-green.ok"
    assert marker.is_file(), "a green run must record WHICH tree it proved"
    assert _run_hook(repo).returncode == 0, "an unchanged follow-up turn must skip the re-run"

    (repo / "test_probe.py").write_text(_RED_TEST + "\n# edit\n", encoding="utf-8")
    porcelain_after = subprocess.run([_GIT, "status", "--porcelain"], cwd=str(repo),
                                     capture_output=True, text=True).stdout
    assert porcelain_after == porcelain_before, (
        "precondition: this case only discriminates while `git status` is byte-identical across the "
        f"edit, got {porcelain_before!r} -> {porcelain_after!r}")
    assert _run_hook(repo).returncode == 2, \
        "a content-only edit slipped past the green marker — the key is not tracking content"


@_needs_shell
def test_stop_hook_still_gates_a_path_git_has_to_quote(tmp_path):
    """git QUOTES a porcelain path containing a space, so the line ends in `"` and not in
    `.py`. With a bare `grep -E '\\.py$'` the hook saw no Python change and allowed the
    stop over a RED suite -- the gate silently not applying to exactly the files whose
    names are unusual. Pytest still collects this name (`test_*.py` globs the space)."""
    repo = _hook_repo(tmp_path, "test_my probe.py", _RED_TEST)
    porcelain = subprocess.run([_GIT, "status", "--porcelain"], cwd=str(repo),
                               capture_output=True, text=True).stdout
    assert '"' in porcelain, f"precondition: git must quote this path, got {porcelain!r}"
    p = _run_hook(repo)
    assert p.returncode == 2, (
        f"a red suite in a quoted-path file was NOT gated (rc={p.returncode}) -- the "
        f"change detector missed it. porcelain={porcelain!r}")
