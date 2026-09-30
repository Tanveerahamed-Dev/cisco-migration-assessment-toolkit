"""Importing the engine must not touch the filesystem; running it must.

WHAT WAS WRONG. ``COLLECT_PARSE_V3_23_0`` ran ``logger = setup_logging()`` at module import, so every
process that merely IMPORTED the engine opened (mode ``w``, then identity-checked and truncated) the
per-working-directory audit log. pytest collection imports it from many test modules, and under
pytest-xdist several workers did that at once in the same working directory: the repository's own
Stop hook (``-n auto``) intermittently failed collection with ``PermissionError: [Errno 13]`` on
``tests/test_axis_registry.py`` and ``Different tests were collected between gw3 and gw2``. An
importer that is not a run (AssessHub helpers, the attestation re-import, a test module) has no audit
log to write.

THE RULE. Import is side-effect-free; ``main()`` installs the run's audit log in the run's working
directory. Each test runs the engine in a fresh interpreter with a fresh working directory, so no
earlier import in this process can mask the behaviour.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENGINE = "COLLECT_PARSE_V3_23_0"


def _engine_log_name() -> str:
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import {_ENGINE} as cp; "
            "print(cp._LOG_FILE_NAME)")
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                          cwd=str(ROOT)).stdout.strip().splitlines()[-1]


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); {code}"],
                          capture_output=True, text=True, cwd=str(cwd), env=env, timeout=300)


def test_importing_the_engine_opens_no_log_and_installs_no_handler(tmp_path):
    log_name = _engine_log_name()
    proc = _run(f"import logging, {_ENGINE}; "
                "print(len(logging.getLogger('CiscoMigrationAutofillV3_14_6').handlers), "
                "len(logging.getLogger('cisco_toolkit').handlers))", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split()[-2:] == ["0", "0"], proc.stdout
    assert not (tmp_path / log_name).exists(), "importing the engine created its audit log"


def test_an_unopenable_log_path_cannot_break_import(tmp_path):
    """The collection-time failure class: whatever makes the audit log unopenable at the moment of
    import (a sharing violation, a read-only path, a directory squatting on the name) must not make
    the IMPORT fail -- only a run needs the log."""
    log_name = _engine_log_name()
    (tmp_path / log_name).mkdir()           # the log path cannot be opened as a file
    proc = _run(f"import {_ENGINE}; print('imported')", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("imported")


def test_main_still_installs_the_run_audit_log_in_the_run_directory(tmp_path):
    log_name = _engine_log_name()
    proc = _run(f"import {_ENGINE} as cp; sys.argv = ['cisco-assess', '--no-such-flag']; cp.main()", tmp_path)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)     # argparse refused the flag ...
    assert (tmp_path / log_name).is_file(), "main() did not install the run's audit log"  # ... after setup


def test_main_refuses_to_run_when_its_audit_log_cannot_be_opened(tmp_path):
    """Moving the open from import to main() must not turn an unopenable audit log into a silent,
    unlogged run: main() still raises EngineLogOpenError (which serve.py's --run-engine door turns
    into its friendly refusal)."""
    log_name = _engine_log_name()
    (tmp_path / log_name).mkdir()
    proc = _run(f"import {_ENGINE} as cp; sys.argv = ['cisco-assess', '--help']; cp.main()", tmp_path)
    assert proc.returncode != 0
    assert "EngineLogOpenError" in proc.stderr, proc.stderr
