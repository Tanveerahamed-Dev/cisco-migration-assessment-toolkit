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


def test_webapp_un_collection_is_announced_not_silent():
    """...and when it DOES skip, it must say so. `collect_ignore_glob` emits no skip report and
    no reason line, and pytest.ini sets `-q`, so a run that silently dropped ~20 webapp test
    files — the Atlas redaction suite, security hardening, unplug safety — looked exactly like a
    full green one, including to the verify-green Stop hook. Asserted against the guard's own
    state rather than its source text, so the assertion cannot rot into a grep."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        "_webapp_conftest_probe", os.path.join(ROOT, "webapp", "tests", "conftest.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "MISSING_WEB_DEPS"), \
        "the guard no longer publishes which deps are missing — un-collection is silent again"
    assert hasattr(mod, "pytest_report_collectionfinish"), \
        "the guard no longer announces the un-collection to the terminal reporter"
    announced = mod.pytest_report_collectionfinish(None)
    if mod.MISSING_WEB_DEPS:
        assert announced and "NOT COLLECTED" in announced, \
            "web deps are missing but the run says nothing about the dropped suites"
    else:
        assert announced is None, "nothing was dropped, so nothing should be announced"


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
