"""Doctrine-as-tests for the verification gates themselves (Plan A / Move-0.2).

The class this pins: an asset EXISTS but silently sits outside the gate — webapp/tests
lived outside the default suite + Stop hook for months, and the ~2700-line entry module
sat outside the coverage measurement. "Suite green" is only meaningful if what should be
gated actually is; these tests fail the moment a gate un-wires."""
import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
