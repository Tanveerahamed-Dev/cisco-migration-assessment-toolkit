"""Launch the W59 asyncssh interop fixture (``server.py``) as a SUBPROCESS on 127.0.0.1 -- no test functions here.

Shared by ``tests/test_ssh_session_interop.py`` (W59 PR-1) and ``tests/test_legacy_ssh.py`` (W59 PR-2), so neither
test module imports the other (W59 PR-2 review round 3). Moved verbatim from ``tests/test_ssh_session_interop.py``.

The fixture runs from its own virtualenv, built from the hash-pinned ``tools/requirements-ssh-fixture-test.txt``; this
module never imports asyncssh (design section 8). The fixture interpreter's path is read from
``ATLAS_SSH_FIXTURE_PYTHON``. On the legs that provision it the workflow also sets ``ATLAS_SSH_FIXTURE_REQUIRED=1``,
and then a missing fixture FAILS rather than skips, so the interop gate cannot pass vacuously; any other run skips
visibly with the reason.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import uuid
from pathlib import Path

import pytest

FIXTURE_PYTHON_ENV = "ATLAS_SSH_FIXTURE_PYTHON"
FIXTURE_REQUIRED_ENV = "ATLAS_SSH_FIXTURE_REQUIRED"
SERVER = Path(__file__).resolve().parent / "server.py"


def _fixture_python() -> str:
    path = os.environ.get(FIXTURE_PYTHON_ENV, "")
    if path and os.path.isfile(path):
        return path
    reason = (f"SSH interop fixture not provisioned: set {FIXTURE_PYTHON_ENV} to an interpreter of a virtualenv "
              f"built from tools/requirements-ssh-fixture-test.txt (pip install --require-hashes --no-deps)")
    if os.environ.get(FIXTURE_REQUIRED_ENV) == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _read_ready(proc: subprocess.Popen, timeout: float) -> int:
    box = []
    reader = threading.Thread(target=lambda: box.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    line = box[0] if box else ""
    if not line.startswith("READY "):
        proc.kill()
        _out, err = proc.communicate(timeout=15)
        pytest.fail(f"SSH fixture did not start (got {line!r}); stderr tail: {(err or '')[-2000:]}")
    return int(line.split()[1])


@contextlib.contextmanager
def fixture_server(tmp_path: Path, profile: str, *, expect_file: Path | None = None, password: str = "lab"):
    log = tmp_path / f"fixture-{profile}-{uuid.uuid4().hex[:8]}.jsonl"
    cmd = [_fixture_python(), "-I", "-B", str(SERVER), "--profile", profile, "--log", str(log),
           "--password", password]
    if expect_file is not None:
        cmd += ["--expect-file", str(expect_file)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")
    try:
        yield _read_ready(proc, 90), log
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=20)
