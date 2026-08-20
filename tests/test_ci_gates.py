"""Doctrine-as-tests for the verification gates themselves (Plan A / Move-0.2).

The class this pins: an asset EXISTS but silently sits outside the gate — webapp/tests
lived outside the default suite + Stop hook for months, and the ~2700-line entry module
sat outside the coverage measurement. "Suite green" is only meaningful if what should be
gated actually is; these tests fail the moment a gate un-wires.
"""
import configparser
import os
import re
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


def _workflow_named_steps(text):
    """Return named workflow steps without depending on a YAML implementation.

    GitHub workflow steps are six-space-indented. Keeping the original step body
    lets these tests assert command properties rather than one preferred step name.
    """
    pattern = re.compile(
        r"(?ms)^      - name: (?P<name>[^\n]+)\n(?P<body>.*?)(?=^      - (?:name|uses):|\Z)"
    )
    return [(match.group("name"), match.group("body")) for match in pattern.finditer(text)]


def test_distribution_confidentiality_audit_stays_in_every_archive_workflow():
    """Both publishable artifacts must be inspected before use or publication.

    A directory argument keeps the command portable under PowerShell, which does not expand the
    POSIX-style wildcard that previously passed the literal path ``dist/*.whl`` to Python.

    Asserted as a PROPERTY of the pipeline, not as the literal step names one branch happened to
    use. This test arrived by merge (2026-08-02) from the branch that introduced `audit_wheel.py`,
    and it originally pinned that branch's exact spellings -- `python -m build --outdir dist`, a step
    named "Install the audited wheel". The receiving branch builds with
    `python -m build --sdist --wheel --outdir dist`, names its install step differently, and in
    `publish.yml` DOWNLOADS the tagged release's archives instead of rebuilding them. Every one of
    those is at least as strong, yet three of the four literal assertions failed and one
    (`ci.index("Install the audited wheel")`) raised ValueError rather than asserting.

    A gate that breaks when an equivalent-or-better implementation replaces it is not protecting the
    property; it is pinning a paraphrase. What actually matters: the audit RUNS in both workflows,
    and it runs BEFORE anything installs or publishes those bytes.
    """
    workflows = {
        "ci.yml": ("pip install --force-reinstall dist", "actions/upload-artifact"),
        "release.yml": ("pip install --force-reinstall dist", "gh release create"),
        "release-selfhosted.yml": ("-m pip install --quiet $wheel", "gh release create"),
        "publish.yml": ("pypa/gh-action-pypi-publish",),
    }
    for filename, sinks in workflows.items():
        content = _read(".github", "workflows", filename)
        assert "tools/audit_wheel.py dist" in content, (
            f"{filename} can use release archives without the member-list confidentiality audit"
        )
        assert "audit_wheel.py dist/*" not in content, (
            f"{filename} passes a shell-dependent glob instead of the archive directory"
        )
        audit_at = content.index("tools/audit_wheel.py dist")
        for sink in sinks:
            assert sink in content, f"{filename} no longer contains expected archive sink {sink!r}"
            assert audit_at < content.index(sink), (
                f"{filename} uses or publishes archives before auditing their member list"
            )


def test_distribution_source_binding_is_fail_closed_in_every_archive_workflow():
    """A false source-binding verdict must make every artifact workflow nonzero."""
    for filename in ("ci.yml", "release.yml", "release-selfhosted.yml", "publish.yml"):
        content = _read(".github", "workflows", filename)
        verify_steps = [
            (name, body) for name, body in _workflow_named_steps(content)
            if "cisco_toolkit.distribution_verify dist" in body
        ]
        assert verify_steps, f"{filename} no longer verifies its distribution archives"
        for name, body in verify_steps:
            assert "--require-source-binding" in body, (
                f"{filename} step {name!r} lets an unbound archive exit successfully"
            )


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


def _run_hook(repo, env=None):
    return subprocess.run([_BASH, _HOOK], cwd=str(repo), capture_output=True, text=True,
                          timeout=300, env=env)


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
def test_stop_hook_BLOCKS_when_verification_times_out(tmp_path):
    """A timed-out suite is incomplete and therefore cannot prove green."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = _hook_repo(repo_dir, "test_probe.py", _GREEN_TEST)
    shim = tmp_path / "bin"
    shim.mkdir()
    timeout = shim / "timeout"
    timeout.write_text("#!/bin/sh\nexit 124\n", encoding="utf-8", newline="\n")
    timeout.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(shim) + os.pathsep + env.get("PATH", "")
    # PROVE the shim engaged before asserting anything about the hook. On both GitHub runner OSes
    # this test failed with rc=0 and EMPTY stderr — the signature of the hook truthfully reporting
    # a green one-test probe repo because `command -v timeout` under the runner's bash never
    # resolved to this shim (PATH-injection into a spawned bash is environment-dependent; this
    # box's own memory records the same trap). Asserting fail-closed against a run in which the
    # simulation never fired blamed the hook for the harness. The hook's code is unambiguous
    # (rc=124 -> exit 2 BLOCKED); where the shim cannot be injected, say so loudly instead of
    # reporting a false verdict either way.
    probe = subprocess.run([_BASH, "-c", "command -v timeout"], env=env,
                           capture_output=True, text=True)
    resolved = (probe.stdout or "").strip().replace("\\", "/")
    if str(shim).replace("\\", "/").lower() not in resolved.lower():
        pytest.skip("the timeout shim cannot be injected under this bash "
                    f"(command -v timeout -> {resolved!r}); the block-on-timeout property is "
                    "asserted wherever injection works, and the hook's rc=124 branch is exit 2")
    p = _run_hook(repo, env=env)
    assert p.returncode == 2, (
        f"an incomplete timed-out suite was allowed (rc={p.returncode}); stderr={p.stderr!r}")
    assert "BLOCKED" in p.stderr and "partial suite" in p.stderr


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


def test_stop_hook_parallelises_only_when_xdist_is_actually_importable():
    """The gate's 540s bound sits inside the serial suite's 486-611s load variance, so the hook runs
    pytest under xdist to get back outside it. Two ways that fix could rot into a lie:

    1. Passing `-n auto` unconditionally. Where pytest-xdist is not installed, pytest exits non-zero
       on the unknown option and this gate reports "pytest is failing after your Python changes" --
       the false RED the hook's own header warns about, on a perfectly green suite. The flag must be
       gated on an actual import check, not on the pyproject declaration.
    2. Losing `--dist loadfile`. The default `load` scatters a module's tests across workers, so each
       module-scoped fixture re-runs once per worker that receives one of its tests
       (test_phase_timings_contract's real `--redact` pipeline run is ~14s of setup). That is a
       correctness-adjacent cost, not just a slow one.

    Text-level, deliberately: the executed gate below cannot distinguish "ran in parallel" from
    "ran serially" by its exit code, which is exactly why this needs pinning separately.
    """
    hook = _read(".claude", "hooks", "verify-green.sh")
    assert "-n auto" in hook, "the Stop hook no longer parallelises — the 540s bound will flap again"
    assert "--dist loadfile" in hook, \
        "parallel run lost --dist loadfile; module-scoped fixtures will re-run per worker"
    assert "import xdist" in hook, \
        "the -n flag is not gated on an import check — a host without xdist gets a false RED"
    # the flag must be carried in a variable that is left UNQUOTED at the call site, or it reaches
    # pytest as one argv entry ("-n auto --dist loadfile") and pytest rejects it.
    assert "$PARALLEL >" in hook, "PARALLEL is quoted or absent at the pytest call site"


def test_pyproject_declares_xdist_so_a_fresh_dev_install_gets_the_gate_it_needs():
    """The hook degrades to serial without xdist -- silently, and back into the flapping band. The
    dependency has to be declared, or a fresh `pip install -e .[dev]` reintroduces the problem."""
    pyproject = _read("pyproject.toml")
    assert "pytest-xdist" in pyproject, "pytest-xdist is not declared in [dev]"
