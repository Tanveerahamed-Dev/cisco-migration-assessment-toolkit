"""Regression guard for the nightly wrapper (.claude/hooks/nightly-run.sh).

The wrapper is a thin, fail-open shell over the (python-tested) clock rails. The properties that MUST
hold — and that a future edit must not break — are the SAFETY ones:

- a default (dry-run) invocation spends nothing and writes no ledger row;
- a NO-GO preflight stands the run down;
- ``--live`` WITHOUT the arming env refuses to spend.

This shells out to bash, so it skips cleanly where bash isn't on PATH (the wrapper is also manually
verified). It NEVER sets ``ASNE_NIGHTLY_ARMED`` — the armed live path would spend real money and is out
of scope for an automated test.
"""
import datetime
import os
import shutil
import subprocess

import pytest

_BASH = shutil.which("bash")
_ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True).stdout.strip() or None
_SCRIPT = os.path.join(".claude", "hooks", "nightly-run.sh")

pytestmark = pytest.mark.skipif(
    not (_BASH and _ROOT and os.path.exists(os.path.join(_ROOT, _SCRIPT))),
    reason="bash / git toplevel / wrapper script unavailable")


def _run(args, ledger):
    env = dict(os.environ)
    env["NIGHTLY_RUNS_FILE"] = str(ledger)
    env["ASNE_NIGHTLY_NO_BRIEF"] = "1"       # hermetic: no docs/briefings write
    env.pop("ASNE_NIGHTLY_ARMED", None)      # NEVER armed in a test — the live path spends money
    return subprocess.run([_BASH, _SCRIPT, *args], cwd=_ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def test_dry_run_spends_nothing(tmp_path):
    ledger = tmp_path / "n.jsonl"
    p = _run([], ledger)
    assert p.returncode == 0
    assert "DRY-RUN" in p.stdout and "$0 spent" in p.stdout
    assert (not ledger.exists()) or ledger.read_text() == ""     # ledger untouched


def test_nogo_preflight_stands_down(tmp_path):
    ledger = tmp_path / "n.jsonl"
    now = datetime.datetime.now()                                # RECENT failures -> still in cooldown
    today = now.date().isoformat()
    ts = now.isoformat(timespec="seconds")
    row = ('{"date":"%s","ts":"%s","outcome":"fail","cost_usd":0.3,"turns":2,'
           '"actions":0,"commit":"c","notes":"x"}') % (today, ts)
    ledger.write_text("\n".join([row] * 3) + "\n")               # 3 fresh failures -> breaker OPEN
    p = _run([], ledger)
    assert p.returncode == 0
    assert "NO-GO" in p.stdout and "standing down" in p.stdout


def test_live_without_arming_refuses(tmp_path):
    ledger = tmp_path / "n.jsonl"
    p = _run(["--live"], ledger)
    assert p.returncode == 0
    assert "refusing to spend" in p.stdout
    assert (not ledger.exists()) or ledger.read_text() == ""     # nothing recorded
