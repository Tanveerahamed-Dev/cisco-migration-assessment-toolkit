"""Round-5 pass over the automation layer: the hooks nobody ever RAN, and the guards that
covered only part of their class.

Companions: tests/test_hooks_automation.py (the settings.json hooks, executed) and
tests/test_ci_gates.py (verify-green.sh, executed). Round 2 measured 4 of 9 hooks; after it,
7 of the 10 command entries in .claude/settings.json were executed by some test. This file
closes the remaining three and two partial-class guards. Everything here was reproduced by
running the thing, on 2026-07-28:

* **session-brief.sh (SessionStart) was executed by no test at all** — the only mention of it
  anywhere in the suite is a prose comment in tests/test_ssot_registry.py. Its python body ends
  in ``2>/dev/null || true``, the exact swallow that kept the UserPromptSubmit hook dead for
  months. Measured with a failing interpreter first on PATH: **0 bytes on stdout, 0 bytes on
  stderr, exit 0**. Nothing in the repo could tell that apart from a healthy run.
* **statusline.sh was executed by no test** — it degrades to a bare ``ASNE v<version>`` line
  (measured: 12 bytes) that silently drops the branch and the model.
* **No test checked that the .sh files settings.json names actually exist.** Measured:
  ``bash .claude/hooks/does-not-exist.sh`` exits **127**, and only exit 2 blocks a Stop hook —
  so renaming verify-green.sh removes the repo's load-bearing gate with no signal whatsoever.
* The root ``conftest.py`` is a REGISTERED PLUGIN for ``python -m pytest webapp/tests`` (proven
  with ``--trace-config``) but was absent from webapp-ci's ``paths:`` filter.
* The ``continue-on-error`` / ``|| true`` guard in tests/test_hooks_automation.py iterates
  ci.yml and webapp-ci.yml only — release.yml and publish.yml were unguarded.

The former timeout fail-open is pinned deterministically in ``test_ci_gates.py`` by placing a
``timeout`` shim first on PATH. No wall-clock race is required: exit 124 must block exactly like
any other incomplete verification.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".claude", "hooks")
AGENTS = os.path.join(ROOT, ".claude", "agents")

_BASH = shutil.which("bash")
_needs_bash = pytest.mark.skipif(not _BASH, reason="bash unavailable")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _settings():
    return json.loads(_read(".claude", "settings.json"))


def _run_hook(name, stdin_bytes=b"", cwd=ROOT):
    """Run a hook script the way Claude Code does and decode as UTF-8 EXPLICITLY.

    Not ``text=True``: statusline.sh emits U+1F6F0 and this platform's locale encoding is
    cp1252, so the convenience decoder raises UnicodeDecodeError and the test dies of its own
    harness rather than of the hook.
    """
    p = subprocess.run([_BASH, os.path.join(HOOKS, name)], cwd=cwd, input=stdin_bytes,
                       capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


# ------------------------------------------------------- the hooks no test ever executed

@_needs_bash
def test_session_start_hook_actually_emits_the_brief():
    """SessionStart is how every session learns the engagement state, the specialist roster and
    the doctrine — and it was the last settings.json hook that nothing in the suite ran.

    Its whole python body is a heredoc ending ``2>/dev/null || true``: a broken interpreter, an
    import error or a syntax slip anywhere in those 120 lines produces zero bytes and exit 0.
    That is indistinguishable from a healthy run to everything except this assertion.
    """
    rc, out, err = _run_hook("session-brief.sh")
    assert rc == 0, "the SessionStart hook must never wedge a session (rc=%d, stderr=%r)" % (
        rc, err[-300:])
    assert out.strip(), (
        "the SessionStart hook emitted NOTHING — the engagement brief is a silent no-op, exactly "
        "the failure that kept the UserPromptSubmit hook dead (stderr=%r)" % err[-300:])
    payload = json.loads(out)
    hso = payload["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    # Structure, not this box's values: a brief that lost its roster/doctrine still "emits".
    for required in ("Toolkit version:", "Specialist roster", "Commands:", "Doctrine:"):
        assert required in ctx, "the brief no longer carries %r: %r" % (required, ctx[:200])


@_needs_bash
def test_statusline_hook_emits_more_than_its_degraded_fallback():
    """statusline.sh was reached by exactly one static string assertion and executed by nothing.

    It has a real fallback (``|| echo "ASNE v$ver"``), so a dead interpreter still prints
    something — measured at 12 bytes — while silently dropping the branch and the model. Asserting
    "non-empty" would therefore pass on the degraded path; assert the parts only the python body
    can produce.
    """
    payload = json.dumps({"model": {"display_name": "TestModel9"},
                          "workspace": {"current_dir": ROOT}}).encode("utf-8")
    rc, out, err = _run_hook("statusline.sh", stdin_bytes=payload)
    assert rc == 0, "the status line must never fail (rc=%d, stderr=%r)" % (rc, err[-200:])
    assert out.strip(), "the status line emitted nothing at all"
    assert "TestModel9" in out, (
        "the status line dropped the model — it is running its degraded fallback, so the python "
        "body is dead: %r" % out)
    version = re.search(r'^version *= *"([^"]+)"', _read("pyproject.toml"), re.M).group(1)
    assert version in out, "the status line lost the toolkit version: %r" % out


@_needs_bash
def test_every_hook_script_named_by_settings_json_exists():
    """A settings.json entry pointing at a MISSING script fails silently in the worst possible
    direction. Measured: ``bash .claude/hooks/does-not-exist.sh`` exits 127, and Claude Code
    blocks a Stop hook only on exit 2 — so renaming verify-green.sh (or a typo in this path)
    deletes the repo's load-bearing test gate while every turn keeps ending normally.

    Nothing read these paths before: the round-2 tests invoke the hook FILES by name from
    .claude/hooks/, which stays green no matter what settings.json points at.
    """
    settings = _settings()
    commands = []
    for entries in (settings.get("hooks") or {}).values():
        for entry in entries:
            commands += [h["command"] for h in entry.get("hooks", []) if h.get("type") == "command"]
    sl = settings.get("statusLine") or {}
    if sl.get("type") == "command":
        commands.append(sl["command"])
    assert commands, "settings.json declares no hook commands at all"

    referenced = set()
    for cmd in commands:
        referenced.update(re.findall(r"(\.claude/hooks/[\w.-]+\.(?:sh|py))", cmd))
    assert referenced, "no hook SCRIPT is referenced from settings.json — did the paths change?"

    missing = sorted(r for r in referenced if not os.path.isfile(os.path.join(ROOT, r)))
    assert not missing, (
        "settings.json references hook script(s) that do not exist: %s — `bash <missing>` exits "
        "127, which does NOT block a Stop hook, so the gate would vanish silently" % missing)


# ------------------------------------------------------------- partial-class guards, widened

def test_release_and_publish_workflows_do_not_swallow_a_failure():
    """tests/test_hooks_automation.py pins this for ci.yml and webapp-ci.yml only. release.yml and
    publish.yml were left out — and they are the two whose failure is least visible, because they
    run on a tag / manual dispatch rather than on a PR anyone is watching. A
    ``continue-on-error: true`` on the PyPI upload would make a failed publish report green.

    (`gh release view ... >/dev/null 2>&1` inside release.yml's `if` is the intentional
    idempotency probe, not a swallowed failure — this reads the YAML KEY and `|| true`, so that
    line is not matched.)
    """
    for wf_name in ("release.yml", "publish.yml"):
        wf = _read(".github", "workflows", wf_name)
        body = "\n".join(ln for ln in wf.splitlines() if not ln.strip().startswith("#"))
        keys = [ln for ln in body.splitlines()
                if ln.strip().lstrip("- ").startswith("continue-on-error:")]
        assert not keys, (
            "%s marks %d step(s) continue-on-error — a failed release/publish would report green"
            % (wf_name, len(keys)))
        assert "|| true" not in body, "%s swallows a step failure with `|| true`" % wf_name


def test_webapp_ci_scope_covers_the_root_conftest():
    """The backend job is ``python -m pytest webapp/tests``, and pytest's confcutdir is the
    rootdir — so the ROOT conftest.py loads for that command. Proven 2026-07-28 with
    ``pytest webapp/tests --collect-only --trace-config``, which reports:

        PLUGIN registered: <module 'conftest' from '...\\Enhancements\\conftest.py'>
        PLUGIN registered: <module 'conftest' from '...\\Enhancements\\webapp\\tests\\conftest.py'>

    It installs an autouse fixture on every backend test and mutates sys.path, so breaking it
    must engage both the post-merge push filter and the PR classifier. The PR workflow itself is
    unconditional so these job contexts remain safe to make required.
    """
    assert os.path.isfile(os.path.join(ROOT, "conftest.py")), \
        "precondition: this repo has a root conftest.py"
    wf = _read(".github", "workflows", "webapp-ci.yml")
    lists = [ln for ln in wf.splitlines() if ln.strip().startswith("paths:")]
    assert len(lists) == 1, "only the push event may retain a path filter: %s" % lists
    entries = json.loads(lists[0].split("paths:", 1)[1].strip())
    assert "conftest.py" in entries, (
        "the root conftest.py is a registered plugin for the backend job but does not trigger "
        "post-merge webapp-ci: %s" % entries)
    classifier = _read(".github", "scripts", "classify_webapp_ci_scope.py")
    assert '"conftest.py"' in classifier, "the PR scope classifier omits root conftest.py"


# --------------------------------------------------- read-only agents vs their own instructions
# tests/test_proposer_verifier_guard.py pins the frontmatter `tools:` allowlist. That is the
# DECLARED constraint. This pins the other half: the agent's own prose must not instruct it to do
# the thing the declaration forbids. CLAUDE.md is explicit that read-only here is a TRUST model,
# not a sandbox — every one of these agents holds Bash, so the prompt IS the control.

#: The agents whose frontmatter carries no Edit/Write (see test_proposer_verifier_guard.py).
_READONLY_AGENTS = ("assessment-analyst", "config-security-auditor", "deliverable-qa-reviewer",
                    "nrfu-validator", "topology-reachability-analyst")

#: Forms of `cisco-assess` that provably cannot open an SSH session to a device.
_OFFLINE_FORMS = ("--no-collect", "--compare", "--trend")


@pytest.mark.parametrize("agent", _READONLY_AGENTS)
def test_readonly_agent_never_tells_itself_to_run_a_live_collection(agent):
    """CLAUDE.md: "A bare ``cisco-assess`` SSHes to live gear — only run a live collection when
    explicitly asked." So a read-only agent that tells itself to run the engine, in any form that
    could collect, must also carry the no-unrequested-collection guardrail.

    The gap this closes (measured by reading the two files side by side): assessment-analyst
    carried that guardrail TWICE — in its Method and again in its Guardrails — while
    config-security-auditor said only "Run an assessment", with no ``--no-collect`` guidance
    anywhere in the file and a Guardrails block that stopped at "never write to devices". A
    read-only SSH collection writes nothing to a device, so it satisfied every word of that
    agent's stated constraint while SSHing into production.
    """
    path = os.path.join(AGENTS, agent + ".md")
    assert os.path.isfile(path), "%s: agent file missing — the read-only roster changed" % agent
    text = _read(".claude", "agents", agent + ".md")

    engine_lines = [ln for ln in text.splitlines()
                    if "cisco-assess" in ln or re.search(r"\brun (a |an )?\w*\s?assessment",
                                                         ln, re.I)]
    collecting = [ln for ln in engine_lines
                  if not any(form in ln for form in _OFFLINE_FORMS)]
    if not collecting:
        return  # only offline forms (or no engine invocation at all) — nothing to guard

    lowered = text.lower()
    assert "live collection" in lowered and "explicit" in lowered, (
        "%s is declared read-only and instructs itself to run the engine in a form that can SSH "
        "to live gear (%r) but carries NO 'never run a live collection without explicit "
        "instruction' guardrail. 'Never write to devices' does not cover a read-only SSH session."
        % (agent, collecting[0].strip()[:120]))
