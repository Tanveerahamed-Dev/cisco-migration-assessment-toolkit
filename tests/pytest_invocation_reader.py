"""The ONE reader of a CI step's pytest invocations (W5b, S-CI-V2).

tests/test_ssot_registry.py (the CI-leg fetch-depth guard) and webapp/tests/test_scope_mount.py (the
legs that must run the /scope pins) both ask which repository paths a workflow step's pytest
collects. They read it here, so the two answers cannot drift apart (they had: one copy knew the
``--cov*`` options and the other read ``--cov webapp`` as a collected path).

Not a test module: the root conftest.py puts tests/ on sys.path, so both suites import it by name.
"""
from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

#: The repository root, whose pytest.ini names what a bare `pytest` collects.
REPO = Path(__file__).resolve().parent.parent

#: pytest options whose value is the NEXT token, so that value is not read as a collected path
#: (pytest's own, pytest-xdist's ``-n`` and pytest-cov's ``--cov*``).
PYTEST_VALUE_OPTIONS = frozenset({"-p", "-k", "-m", "-o", "-c", "-W", "-n", "--ignore", "--deselect",
                                  "--rootdir", "--basetemp", "--confcutdir", "--junitxml",
                                  "--maxfail", "--durations", "--tb", "--ignore-glob", "--cov",
                                  "--cov-report", "--cov-fail-under", "--cov-config"})


def default_testpaths() -> list[str]:
    """What a bare `pytest` collects here: pytest.ini's testpaths (or, without one, the root)."""
    config = configparser.ConfigParser()
    config.read(REPO / "pytest.ini", encoding="utf-8")
    return config.get("pytest", "testpaths", fallback=".").split()


def pytest_invocations(run: str, working_directory: str = ".") -> list[list[str]]:
    """Every pytest invocation in one step's script, as the repository paths it collects (pytest.ini's
    testpaths when it names none).

    A line continuation is joined first, exactly as the shell joins it, so an invocation whose paths
    sit on the next line is read whole (QF-V2-4): bash DELETES an unescaped backslash that is the
    last character before a line feed, together with the line feed; PowerShell reads an unescaped
    backtick directly before a line feed as a blank. Anything between the escape and the line feed
    -- a blank, a CR -- makes it no continuation at all (RQF-V1-5, measured in both shells). An
    option that takes a value consumes the next token (`-p no:cacheprovider` names no path), and
    every interpreter spelling counts (`python -m pytest`, `& "...python.exe" -m pytest`, a bare
    `pytest`)."""
    run = re.sub(r"(?<!\\)((?:\\\\)*)\\\n", r"\1", run)
    run = re.sub(r"(?<!`)((?:``)*)`\n", r"\1 ", run)
    invocations = []
    for match in re.finditer(r"(?:-m\s+pytest|(?:^|[\s;&|(])pytest)(?=[\s'\"]|$)([^\n;&|'\"]*)",
                             run, re.MULTILINE):
        paths, value_next = [], False
        for token in match.group(1).split():
            if value_next:
                value_next = False
            elif token in PYTEST_VALUE_OPTIONS:
                value_next = True
            elif not token.startswith("-"):
                paths.append(token.split("::", 1)[0])
        invocations.append([os.path.normpath(os.path.join(working_directory, path)).replace("\\", "/")
                            for path in (paths or default_testpaths())])
    return invocations
