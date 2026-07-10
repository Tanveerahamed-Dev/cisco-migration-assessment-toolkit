"""Tests for the P0-8 vault-guard shell lane (.claude/hooks/vault_guard_bash.py + .sh).

ADR 0001 (docs/decisions/0001-two-store-knowledge-architecture.md): repo sessions never
write the personal vault at C:\\Vaults\\brain. vault-guard.sh already blocks the
Write|Edit|NotebookEdit tools; P0-8 adds a PreToolUse hook on the Bash/PowerShell tools
that blocks shell WRITE/DELETE intent read off the command string. Pinned here:

1. the acceptance triple from the master plan task (docs/architect-master-plan-2026-07-10.md
   P0-8): `cat > /c/Vaults/brain/x` BLOCKED; `ls /c/Vaults/brain` (read) and
   `cat > /tmp/x` (non-vault write) PASS;
2. the decision function across spellings (case, slash style, MSYS//cygdrive/UNC
   prefixes), operations (redirections, tee/cp/mv/rm/rmdir/touch/mkdir, sed -i,
   PowerShell cmdlets + aliases), sibling-path non-matches, and the DECLARED
   recall-over-precision trade (write token + vault mention anywhere = block);
3. the end-to-end .sh contract: exit 2 + ADR-0001 stderr on block, exit 0 on pass,
   exit 0 (fail-open) on malformed / empty / command-less stdin.

Nothing here touches C:\\Vaults\\brain — commands are classified as strings, never run.
The guard is BEST-EFFORT by design (session-handoff HR-005 residuals a/b): these tests
pin the promised floor, they do not claim obfuscation-proofness.
"""
import json
import shutil
import subprocess
import sys
from importlib import util as _importlib_util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PY = REPO_ROOT / ".claude" / "hooks" / "vault_guard_bash.py"
HOOK_SH_REL = ".claude/hooks/vault-guard-bash.sh"


def _load_guard():
    spec = _importlib_util.spec_from_file_location("vault_guard_bash", HOOK_PY)
    mod = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()


# ---------------------------------------------------------------------------
# 1) decision function — commands that MUST block
# ---------------------------------------------------------------------------

BLOCKED = [
    # the master-plan acceptance case, verbatim
    "cat > /c/Vaults/brain/x",
    # redirections, every spelling/slash style
    "echo hi >> C:\\Vaults\\brain\\inbox.md",
    "echo hi>c:/vaults/brain/x",
    'printf x > "C:/Vaults/Brain/notes/today.md"',
    "some-tool 2> /c/vaults/brain/err.log",
    "run &> C:\\Vaults\\brain\\all.log",
    "type nul > \\\\?\\C:\\Vaults\\brain\\x",
    "cmd >> //c/vaults/brain/log 2>&1",
    "wc -l < /cygdrive/c/vaults/brain/a.md > /cygdrive/c/vaults/brain/count",
    # tee / coreutils writers
    "echo x | tee /c/Vaults/brain/x",
    "tee -a c:/vaults/brain/log.md < notes.txt",
    "cp lesson.md C:\\Vaults\\brain\\inbox\\",
    "mv /tmp/x /c/VAULTS/BRAIN/y",
    "rm -rf C:/Vaults/brain/old",
    "rmdir c:\\vaults\\brain\\tmp",
    "touch /c/vaults/brain/new.md",
    "mkdir -p C:/Vaults/brain/new-area",
    "dd if=/dev/zero of=/c/vaults/brain/blob bs=1 count=1",
    "rsync -a notes/ /c/vaults/brain/notes/",
    # sed only blocks in-place
    "sed -i 's/a/b/' C:\\Vaults\\brain\\page.md",
    "sed --in-place=.bak -e s/a/b/ /c/vaults/brain/p.md",
    # PowerShell cmdlets (spec'd trio + family) and an alias
    'powershell -Command "Set-Content -Path C:\\Vaults\\brain\\x -Value hi"',
    "Out-File -FilePath C:\\Vaults\\brain\\x -InputObject hi",
    "Remove-Item -Recurse -Force C:\\Vaults\\brain\\old",
    'Add-Content C:/Vaults/brain/log.md "line"',
    "New-Item -ItemType File C:\\Vaults\\brain\\x",
    "ri C:\\Vaults\\brain\\stale.md",
    # cd-into-vault then a relative write — caught by the loose token rule
    "cd /c/vaults/brain && rm stale.md",
    # DECLARED recall-over-precision trade: write token present, vault only read
    "diff /c/vaults/brain/a.md b.md && cp b.md /tmp/",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_write_intent_blocks(command):
    reason = guard.classify(command)
    assert reason, "must block: %r" % command


# ---------------------------------------------------------------------------
# 2) decision function — commands that MUST pass
# ---------------------------------------------------------------------------

ALLOWED = [
    # the master-plan acceptance pair, verbatim
    "ls /c/Vaults/brain",
    "cat > /tmp/x",
    # reads of the vault (out of scope for this hook by task boundary)
    "ls -la C:\\Vaults\\brain",
    "cat /c/vaults/brain/notes.md",
    "grep -rn lesson C:/Vaults/brain",
    "head -5 '/c/vaults/brain/daily/2026-07-10.md'",
    "diff /c/vaults/brain/a.md /c/vaults/brain/b.md",
    "sed -n 1,10p /c/vaults/brain/x.md",
    "Get-Content C:\\Vaults\\brain\\notes.md",
    # writes that never mention the vault
    "rm -rf build/ dist/",
    "cp a.md b.md",
    "Set-Content -Path out/report.txt -Value done",
    "git status",
    "python -m pytest -q",
    # words near-missing the path are not the path
    "echo 'the brain vault lives under Vaults' > /tmp/notes.md",
    # sibling paths are NOT the vault
    "ls C:\\Vaults\\brainstorm",
    "cat c:/vaults/brainpower/x.md",
    "rm -rf C:/Vaults/brain-archive/old",
    # degenerate inputs
    "",
    None,
]


@pytest.mark.parametrize("command", ALLOWED)
def test_reads_and_non_vault_pass(command):
    assert guard.classify(command) is None, "must pass: %r" % command


# ---------------------------------------------------------------------------
# 3) hook process contract — python entrypoint (runs everywhere, no bash needed)
# ---------------------------------------------------------------------------

def _run_py(stdin_text):
    return subprocess.run(
        [sys.executable, str(HOOK_PY)],
        input=stdin_text.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )


def test_py_entrypoint_block_verdict_and_exit0():
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "cat > /c/Vaults/brain/x"}}
    )
    proc = _run_py(payload)
    assert proc.returncode == 0  # python NEVER exits nonzero; the .sh maps BLOCK -> 2
    assert proc.stdout.decode().startswith("BLOCK:")


def test_py_entrypoint_pass_is_silent():
    for cmd in ("ls /c/Vaults/brain", "cat > /tmp/x"):
        proc = _run_py(json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}))
        assert proc.returncode == 0 and proc.stdout == b"", cmd


def test_py_entrypoint_fails_open_on_garbage():
    for stdin_text in ("not json {{{", "", json.dumps({"tool_input": {}})):
        proc = _run_py(stdin_text)
        assert proc.returncode == 0 and proc.stdout == b"", repr(stdin_text)


# ---------------------------------------------------------------------------
# 4) hook process contract — the real .sh wrapper (exit 2 = block, else 0)
# ---------------------------------------------------------------------------

_BASH = shutil.which("bash")


def _bash_usable():
    if not _BASH:
        return False
    try:  # a WSL stub without a distro resolves but cannot run — probe, don't trust
        probe = subprocess.run(
            [_BASH, "-c", "echo ok"], capture_output=True, timeout=30
        )
        return probe.returncode == 0 and b"ok" in probe.stdout
    except Exception:
        return False


needs_bash = pytest.mark.skipif(
    not _bash_usable(), reason="no usable bash on this host (hook targets Git Bash/CI)"
)


def _run_hook_sh(stdin_text):
    return subprocess.run(
        [_BASH, HOOK_SH_REL],
        input=stdin_text.encode("utf-8"),
        capture_output=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


@needs_bash
def test_sh_blocks_vault_write_with_exit_2():
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "cat > /c/Vaults/brain/x"}}
    )
    proc = _run_hook_sh(payload)
    assert proc.returncode == 2
    err = proc.stderr.decode("utf-8", "replace")
    assert "BLOCKED" in err and "ADR 0001" in err


@needs_bash
def test_sh_blocks_powershell_tool_lane():
    payload = json.dumps(
        {
            "tool_name": "PowerShell",
            "tool_input": {"command": "Set-Content -Path C:\\Vaults\\brain\\x -Value hi"},
        }
    )
    assert _run_hook_sh(payload).returncode == 2


@needs_bash
def test_sh_passes_reads_and_non_vault_writes():
    for cmd in ("ls /c/Vaults/brain", "cat > /tmp/x"):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        proc = _run_hook_sh(payload)
        assert proc.returncode == 0, cmd


@needs_bash
def test_sh_fails_open_on_malformed_stdin():
    for stdin_text in ("not json {{{", "", json.dumps({"tool_input": {}})):
        proc = _run_hook_sh(stdin_text)
        assert proc.returncode == 0, repr(stdin_text)
