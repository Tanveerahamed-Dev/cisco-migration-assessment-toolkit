"""Round-7 guards for the four `.claude/` files no earlier review round executed.

Round 5 audited `.claude/` but recorded in its own coverage note that it did NOT examine
these: `morning-briefing.sh` and `nightly-run.sh` were "not executed by me" (neither is
wired into settings.json, so the per-hook execution table skipped them),
`vault_guard_bash.py` was "not read — exercised only through vault-guard-bash.sh", and
`launch.json` was never opened. Two of the four are the highest-consequence kind: a
security guard and an unattended scheduled run.

Everything pinned here was MEASURED first by driving the real file, then fixed:

1. vault_guard_bash.py — 82 candidate command strings through the real `classify()`.
   29 write/delete commands against the vault passed the guard. Three classes:
   UNC spellings of the vault root, `.`/`..` traversal, and write verbs the token list
   never had (git, curl/wget, tar/unzip, find -delete, attrib/icacls). Also pinned: the
   precision the fix must NOT trade away — including one false positive the first draft
   of the fix caused and this file now prevents returning.
2. morning-briefing.sh — with the interpreter broken it wrote 0 bytes to stdout, 0 to
   stderr and exited 0, in BOTH raw and --session mode: byte-identical to a healthy quiet
   day. That is the "absence rendered as health" class, on the instrument whose whole job
   is to tell you what is wrong.
3. nightly-run.sh — an ARMED run that ran and failed exited 0, so a scheduler records a
   broken unattended pass as success; and its `|| echo "(produced nothing)"` fallback was
   unreachable dead code, so a dead assembler shipped an EMPTY payload to the model.
4. launch.json — the `explorer` config served the repo ROOT (client snapshots,
   deliverables, evidence) on 0.0.0.0, every interface, unauthenticated.

Nothing here touches C:\\Vaults\\brain: commands are classified as strings, never run.
No test in this file spends money or reaches the network — the nightly's live path is
driven with a STUBBED claude CLI behind an explicit resolution interlock.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from importlib import util as _importlib_util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_PY = REPO_ROOT / ".claude" / "hooks" / "vault_guard_bash.py"
BRIEFING_SH = REPO_ROOT / ".claude" / "hooks" / "morning-briefing.sh"
NIGHTLY_SH = REPO_ROOT / ".claude" / "hooks" / "nightly-run.sh"
LAUNCH_JSON = REPO_ROOT / ".claude" / "launch.json"


def _load_guard():
    spec = _importlib_util.spec_from_file_location("r7_vault_guard_bash", GUARD_PY)
    mod = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()


# ===========================================================================
# 1) vault_guard_bash.py — spellings of the vault root that reached it
# ===========================================================================

ALTERNATE_SPELLINGS = [
    (r"cp x \\localhost\C$\Vaults\brain\a.md", "UNC admin share"),
    (r"cp x \\127.0.0.1\C$\Vaults\brain\a.md", "UNC admin share via the loopback IP"),
    (r"cp x \\?\UNC\localhost\C$\Vaults\brain\a.md", "extended-length UNC"),
    (r"rm -rf \\localhost\C$\Vaults\brain", "UNC admin share, recursive delete"),
    (r"cp x C:\Vaults\other\..\brain\a.md", "'..' through a SIBLING directory"),
    (r"cp x C:\Users\..\Vaults\brain\a.md", "'..' from another top-level directory"),
    (r"cp x C:\Vaults\.\brain\a.md", "'.' segment"),
    ("rm -rf /c/Vaults/../Vaults/brain", "'..' onto itself"),
    (r"echo hi > \\localhost\C$\Vaults\brain\a.md", "redirect into the UNC spelling"),
]


@pytest.mark.parametrize("command,why", ALTERNATE_SPELLINGS,
                         ids=[w for _, w in ALTERNATE_SPELLINGS])
def test_alternate_spellings_of_the_vault_root_are_blocked(command, why):
    """Every one of these reaches C:\\Vaults\\brain and every one passed the guard.

    The pre-fix pattern demanded the literal prefix `c:/` or `/c/` immediately before
    `vaults/brain`, so a UNC admin share (`\\\\host\\C$\\...`) and any path arriving
    through a `.`/`..` segment simply did not look like the vault.
    """
    assert guard.classify(command), "%s must block (%s)" % (command, why)


UNRECOGNISED_WRITE_VERBS = [
    (r"git -C C:\Vaults\brain checkout -- .", "git checkout DISCARDS uncommitted vault work"),
    (r"git -C C:\Vaults\brain clean -fdx", "git clean DELETES untracked vault files"),
    (r"git -C C:\Vaults\brain reset --hard HEAD~5", "git reset --hard rewrites vault history"),
    (r"git clone https://x/y C:\Vaults\brain\new", "git clone writes into the vault"),
    ("find /c/vaults/brain -name '*.md' -delete",
     "-delete is a FLAG: the 'del' token cannot match it, the boundary excludes a leading dash"),
    (r"curl -o C:\Vaults\brain\a.md https://x/y", "fetch-to-file: writes the vault AND egresses"),
    (r"wget -O C:\Vaults\brain\a.md https://x/y", "fetch-to-file"),
    (r"Invoke-WebRequest https://x -OutFile C:\Vaults\brain\a.md", "fetch-to-file, PowerShell"),
    ("tar -xf a.tar -C /c/vaults/brain", "archive extraction into the vault"),
    ("unzip a.zip -d /c/vaults/brain", "archive extraction into the vault"),
    (r"Expand-Archive a.zip -DestinationPath C:\Vaults\brain", "archive extraction, PowerShell"),
    (r"patch -p1 -d C:\Vaults\brain < a.diff", "in-place patching"),
    (r"attrib +r C:\Vaults\brain\a.md", "metadata write"),
    (r"icacls C:\Vaults\brain /grant Everyone:F", "ACL write"),
    (r"takeown /f C:\Vaults\brain /r", "ownership write"),
]


@pytest.mark.parametrize("command,why", UNRECOGNISED_WRITE_VERBS,
                         ids=[c.split()[0] + "-" + str(i) for i, (c, _) in
                              enumerate(UNRECOGNISED_WRITE_VERBS)])
def test_write_verbs_missing_from_the_token_list_are_blocked(command, why):
    """Plain, unobfuscated commands that mutate the vault and were not recognised.

    These are NOT the declared obfuscation residuals (python -c, base64, cross-call
    state) — every one is an ordinary command a session might reasonably type, and the
    guard's own doctrine is recall over precision.
    """
    assert guard.classify(command), "%s must block (%s)" % (command, why)


STILL_ALLOWED = [
    (r"cp x C:\Vaults\brainstorm\a.md", "sibling directory, not the vault"),
    ("rm -rf C:/Vaults/brain-archive/old", "sibling directory"),
    (r"cat C:\Vaults\brain\a.md", "a pure read — reads are out of scope by task boundary"),
    (r"cat C:\Vaults\brain\a.md > /tmp/out.txt", "a read redirected OUT of the vault"),
    ('grep -rn "vaults/brain" docs/', "the path as a quoted SEARCH STRING, not a path"),
    ("git status", "git with no vault mention at all"),
    ("rm -rf build/ dist/", "a write that never mentions the vault"),
    (r"mkdir -p C:\Users\me\AppData\Local\Temp\t83\Vaults\brain",
     "an unrelated directory that merely ENDS in Vaults\\brain"),
]


@pytest.mark.parametrize("command,why", STILL_ALLOWED, ids=[w[:38] for _, w in STILL_ALLOWED])
def test_precision_is_not_traded_away(command, why):
    """The recall fix must not start blocking reads, siblings or unrelated paths.

    The last row is not hypothetical: the first draft of the fix matched a bare
    `/vaults/brain` with no drive spelling, and immediately blocked a real command
    creating a scratch directory at <temp>/t83/Vaults/brain. A guard that fires on
    unrelated paths is a guard engineers switch off, so the drive spelling stays
    REQUIRED and this row pins that.
    """
    assert guard.classify(command) is None, "%s must pass (%s)" % (command, why)


def test_unc_spelling_blocks_through_the_real_hook_process():
    """The decision function and the hook entrypoint must agree — pin the process contract."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {
        "command": r"cp x \\localhost\C$\Vaults\brain\a.md"}})
    proc = subprocess.run([sys.executable, str(GUARD_PY)], input=payload.encode("utf-8"),
                          capture_output=True, timeout=60)
    assert proc.returncode == 0                       # python never exits nonzero; .sh maps BLOCK->2
    assert proc.stdout.decode().startswith("BLOCK:")


def test_declared_residuals_are_declared_not_silently_absent():
    """Coverage honesty: the interpreter one-liner still passes, and the module SAYS so.

    This asserts the limitation is documented rather than discovered later by someone
    who assumed the guard was complete. If a future change closes the hole, this test
    fails and the docstring must be updated with it.
    """
    assert guard.classify("python -c \"open('C:/Vaults/brain/x','w').write('h')\"") is None
    doc = (guard.__doc__ or "")
    assert "python -c" in doc and "MEASURED residuals" in doc, (
        "the module must declare the interpreter-one-liner residual it cannot catch")


# ===========================================================================
# 2) morning-briefing.sh — the silent-degrade path
# ===========================================================================

_BASH = shutil.which("bash")
_GIT = shutil.which("git")


def _bash_usable():
    if not _BASH:
        return False
    try:  # a WSL stub without a distro resolves but cannot run — probe, don't trust
        probe = subprocess.run([_BASH, "-c", "echo ok"], capture_output=True, timeout=30)
        return probe.returncode == 0 and b"ok" in probe.stdout
    except Exception:
        return False


needs_bash = pytest.mark.skipif(
    not (_bash_usable() and _GIT), reason="no usable bash/git (these hooks target Git Bash/CI)")


def _make_failing_python_shim(tmp_path):
    """A directory holding every interpreter name the hooks try, all failing.

    ``py`` is in this list because the hooks now fall back to the Windows launcher when
    ``python``/``python3`` resolve to something that does not RUN (the Microsoft Store
    App-Execution-Alias stub — see .claude/hooks/*.sh). Shadowing only python/python3 left a
    WORKING interpreter reachable, so the hook produced a perfectly healthy briefing and the
    "degraded run must be loud" assertion below was testing a scenario that no longer existed.
    A fixture that no longer manufactures its own precondition is the quietest way for a test
    to stop testing anything.
    """
    shim = tmp_path / "shim"
    shim.mkdir()
    for name in ("python", "python3", "py"):
        p = shim / name
        p.write_text("#!/bin/sh\necho 'simulated interpreter failure' >&2\nexit 1\n",
                     encoding="utf-8")
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def _env_with_shim(shim):
    env = dict(os.environ)
    env["PATH"] = str(shim) + os.pathsep + env["PATH"]
    env.pop("ASNE_BRIEF_MODE", None)
    return env


def _assert_shim_is_honoured(shim, env):
    """Interlock: prove the broken interpreter is really what the script will resolve.

    Without this the test could pass for the wrong reason (or, worse, quietly stop
    testing anything) if PATH injection were ignored on some host.
    """
    for name in ("python", "python3", "py"):
        p = subprocess.run([_BASH, "-c", "command -v %s || true" % name], env=env,
                           capture_output=True, text=True, timeout=60)
        assert shim.name in p.stdout, (
            "PATH injection was not honoured by bash for %r (resolved %r); this test cannot "
            "simulate a broken interpreter on this host. Every name the hooks try must be "
            "shadowed — one reachable working interpreter and the 'degraded' scenario silently "
            "becomes a healthy one." % (name, p.stdout.strip()))


@needs_bash
def test_briefing_degraded_run_is_loud_and_never_zero_bytes(tmp_path):
    """A dead assembler must not be byte-identical to a healthy quiet morning.

    Measured before the fix: exit 0, 0 bytes on stdout, 0 bytes on stderr, in both
    modes. A SessionStart hook wired to this would inject nothing and the session would
    start believing it had been briefed.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([_GIT, "init", "-q"], cwd=repo, check=True)
    shim = _make_failing_python_shim(tmp_path)
    env = _env_with_shim(shim)
    _assert_shim_is_honoured(shim, env)

    for args in ([], ["--session"]):
        p = subprocess.run([_BASH, str(BRIEFING_SH), *args], cwd=repo, env=env,
                           capture_output=True, text=True, timeout=180)
        label = "--session" if args else "raw"
        assert p.returncode == 0, "must stay fail-open (%s): rc=%s" % (label, p.returncode)
        assert p.stdout.strip(), (
            "ZERO BYTES on stdout with a broken interpreter (%s) — indistinguishable "
            "from a healthy briefing that found nothing to report" % label)
        assert "UNAVAILABLE" in p.stdout, (
            "the degraded run must SAY it is degraded (%s), got: %r" % (label, p.stdout[:200]))
        assert p.stderr.strip(), "the degrade must also be visible on stderr (%s)" % label

    # --session output feeds a SessionStart hook, so the degraded form must still parse.
    p = subprocess.run([_BASH, str(BRIEFING_SH), "--session"], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=180)
    payload = json.loads(p.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "UNAVAILABLE" in payload["hookSpecificOutput"]["additionalContext"]


# ===========================================================================
# 3) nightly-run.sh — unattended failure reporting
# ===========================================================================

def _stub_claude(tmp_path, body, rc):
    """A fake `claude` CLI: no network, no spend. Emits *body*, exits *rc*."""
    binp = tmp_path / "cbin"
    binp.mkdir(exist_ok=True)
    p = binp / "claude"
    p.write_text("#!/bin/sh\nprintf '%s' " + json.dumps(body) + "\nexit %d\n" % rc,
                 encoding="utf-8")
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return binp


def _nightly(args, env):
    return subprocess.run([_BASH, str(NIGHTLY_SH), *args], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True, timeout=300)


def _armed_env(tmp_path, binp, ledger):
    env = dict(os.environ)
    env["PATH"] = str(binp) + os.pathsep + env["PATH"]
    env["NIGHTLY_RUNS_FILE"] = str(ledger)      # never the real docs/quality ledger
    env["ASNE_NIGHTLY_NO_BRIEF"] = "1"          # hermetic: no docs/briefings write
    env["APPDATA"] = str(tmp_path / "noappdata")  # kill the desktop-app CLI fallback too
    return env


@needs_bash
def test_a_failed_unattended_run_exits_nonzero(tmp_path):
    """An armed run that RAN AND FAILED must be red to a scheduler.

    The header documents registering this in Windows Task Scheduler, whose only health
    signal is the exit status. Measured before the fix: outcome=fail exited 0, so every
    broken unattended pass recorded "Last Run Result 0x0" with nobody watching.

    Safety: the CLI is STUBBED and an interlock proves the stub is what resolves BEFORE
    the arming env is ever set, so no real CLI can be invoked and nothing is spent.
    """
    binp = _stub_claude(
        tmp_path, '{"is_error":true,"result":"model errored out","total_cost_usd":0.12,'
                  '"num_turns":3}', 1)
    ledger = tmp_path / "ledger.jsonl"
    env = _armed_env(tmp_path, binp, ledger)

    # INTERLOCK: dry-run (spends nothing, never armed) must resolve OUR stub.
    dry = _nightly([], env)
    assert dry.returncode == 0 and "DRY-RUN" in dry.stdout
    resolved = [l for l in dry.stdout.splitlines() if "Resolved claude CLI" in l]
    assert resolved and tmp_path.name in resolved[0], (
        "refusing to arm: the resolved CLI is not the stub (%s)" % (resolved or "missing"))

    env["ASNE_NIGHTLY_ARMED"] = "yes"
    p = _nightly(["--live"], env)
    assert "outcome=fail" in p.stdout, p.stdout[-400:]
    assert p.returncode != 0, (
        "a failed unattended run exited %s — a scheduler cannot tell it from success"
        % p.returncode)
    assert ledger.exists() and '"outcome": "fail"' in ledger.read_text()


@needs_bash
def test_stand_down_paths_stay_fail_open(tmp_path):
    """Fail-open must survive the change everywhere it is load-bearing.

    None of these is a failure, so none may go red: an unarmed --live, and an armed run
    against an UNAUTHENTICATED CLI (a config gap, recorded 'skipped', $0 spent, and
    deliberately never allowed to trip the breaker).
    """
    binp = _stub_claude(
        tmp_path, '{"is_error":true,"result":"Not logged in. Please run /login",'
                  '"total_cost_usd":0,"num_turns":0}', 1)
    ledger = tmp_path / "ledger.jsonl"
    env = _armed_env(tmp_path, binp, ledger)

    unarmed = _nightly(["--live"], env)
    assert unarmed.returncode == 0 and "refusing to spend" in unarmed.stdout

    dry = _nightly([], env)
    resolved = [l for l in dry.stdout.splitlines() if "Resolved claude CLI" in l]
    assert resolved and tmp_path.name in resolved[0], "refusing to arm: stub not resolved"

    env["ASNE_NIGHTLY_ARMED"] = "yes"
    p = _nightly(["--live"], env)
    assert "outcome=skipped" in p.stdout, p.stdout[-400:]
    assert p.returncode == 0, "an unauthenticated CLI is a config gap, not a run failure"


@needs_bash
def test_nightly_payload_says_so_when_the_briefing_is_empty(tmp_path):
    """A dead assembler must not ship an EMPTY payload under a prompt that announces one.

    The wrapper guarded this with `morning-briefing.sh || echo "(produced nothing)"`,
    which could never fire: the briefing is fail-open and ALWAYS exits 0. Measured with
    the assembler degraded, the fallback did not run and the payload length was 0.
    Here the assembler is replaced by a stub that exits 0 and prints nothing — exactly
    what the real one used to do when its interpreter was missing.
    """
    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    subprocess.run([_GIT, "init", "-q"], cwd=repo, check=True)
    shutil.copy(str(NIGHTLY_SH), str(repo / ".claude" / "hooks" / "nightly-run.sh"))
    silent = repo / ".claude" / "hooks" / "morning-briefing.sh"
    silent.write_text("#!/usr/bin/env bash\n# produces nothing, exits 0 — the measured case\nexit 0\n",
                      encoding="utf-8")

    env = dict(os.environ)
    env["NIGHTLY_RUNS_FILE"] = str(tmp_path / "ledger.jsonl")
    env.pop("ASNE_NIGHTLY_NO_BRIEF", None)      # exercise the REAL assembly path
    env.pop("ASNE_NIGHTLY_ARMED", None)         # never armed: dry-run only, $0
    p = subprocess.run([_BASH, ".claude/hooks/nightly-run.sh"], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0 and "DRY-RUN" in p.stdout

    marker = "briefing payload (local, no-egress) ---"
    assert marker in p.stdout, p.stdout[-400:]
    payload = p.stdout.split(marker, 1)[1].split("------------------")[0].strip()
    assert payload, (
        "the briefing payload section is EMPTY — the model would be asked to brief from "
        "nothing, unattended, under a prompt that announces a payload below it")
    assert "produced nothing" in payload, (
        "an empty briefing must be labelled as such in the payload, got: %r" % payload[:200])


# ===========================================================================
# 4) launch.json — what the browser-preview config can start
# ===========================================================================

def test_launch_json_configs_are_loopback_only_and_internally_consistent():
    """No preview server may listen on a routable interface.

    `python -m http.server <port>` serves the CWD — here the repo ROOT, holding client
    snapshots, deliverables and collected evidence — and its bind default is ALL
    INTERFACES, with no auth (measured: netstat showed 0.0.0.0:<port> LISTENING without
    --bind, 127.0.0.1:<port> with it). The other two configs already pinned loopback
    explicitly; this one did not, so the class is guarded rather than the one entry.
    """
    cfg = json.loads(LAUNCH_JSON.read_text(encoding="utf-8"))
    configs = cfg["configurations"]
    assert configs, "launch.json declares no configurations"

    for c in configs:
        name, args = c["name"], [str(a) for a in c.get("runtimeArgs", [])]
        joined = " ".join(args)
        assert "0.0.0.0" not in joined, "%s binds a routable interface" % name
        assert str(c["port"]) in args, (
            "%s declares port %s but never passes it to the command" % (name, c["port"]))

        binds = [args[i + 1] for i, a in enumerate(args)
                 if a in ("--bind", "--host") and i + 1 < len(args)]
        if "http.server" in joined:
            assert binds, (
                "%s uses http.server, whose bind DEFAULT is every interface, without an "
                "explicit --bind — it would serve the repo root to the network" % name)
        for b in binds:
            assert b.startswith("127.") or b == "localhost", (
                "%s binds %r, expected loopback" % (name, b))


def test_launch_json_commands_point_at_things_that_exist():
    """A preview config must not be able to start something unexpected or missing."""
    cfg = json.loads(LAUNCH_JSON.read_text(encoding="utf-8"))
    for c in cfg["configurations"]:
        assert c["runtimeExecutable"] == "python", (
            "%s runs %r; only the python interpreter is expected here"
            % (c["name"], c["runtimeExecutable"]))
        args = [str(a) for a in c.get("runtimeArgs", [])]
        assert args[0] == "-m", "%s must invoke a module with -m, got %r" % (c["name"], args[:2])

    by_name = {c["name"]: [str(a) for a in c["runtimeArgs"]] for c in cfg["configurations"]}
    # the two repo-local entrypoints must actually exist
    assert (REPO_ROOT / "webapp" / "backend" / "app.py").exists()
    assert (REPO_ROOT / "webapp" / "backend" / "serve.py").exists()
    assert "backend.app:app" in by_name["assesshub"]
    assert "webapp.backend.serve" in by_name["atlas"]
