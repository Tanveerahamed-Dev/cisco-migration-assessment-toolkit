"""Tests for the agent-system self-check (cisco_toolkit.selfcheck) — Phase 4.

The self-check is itself a guard, so it must be NON-VACUOUS: a deleted or gutted guard reads RED (not
silently gone), a missing substrate reads RED, an un-evaluable check reads UNKNOWN (never GREEN), and a
healthy repo reads GREEN. Root, now AND memory_dir are injected so every case is deterministic —
per DEC-005, portable pytest must NEVER reference the per-machine real agent-memory store (the
runtime default path is the pin; here every store is synthetic, under tmp or via $AGENT_MEMORY_DIR).
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from cisco_toolkit import memory_guard as MG
from cisco_toolkit import selfcheck as SC

_REAL_LEARNINGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "docs", "quality", "learnings.md")


def _quality_dir(root):
    q = os.path.join(root, "docs", "quality")
    os.makedirs(q, exist_ok=True)
    return q


def _doctrine_root(tmp_path):
    """A portable stand-in for the repo root: CLAUDE.md carries every canonical anchor verbatim, so
    the protected-artifact reconcile never reads the real repo's doctrine from a unit test."""
    root = str(tmp_path)
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS))
    return root


def _prose_body():
    """The artifact shaped like the REAL one: each canonical anchor inside a doctrine SENTENCE.

    The fixture used to write the anchors as a bare list — which is precisely the compressed shape
    D12 forbids, so the store this suite called healthy was itself the counterexample. Keep this
    prose (a fixture that manufactures the precondition proves nothing about the check)."""
    return "\n".join(
        f"- **{cid}.** The pinned invariant is: {anchor}. It is retained verbatim by every "
        f"consolidation pass, never summarised, and reconciles to the doctrine owner in CLAUDE.md."
        for cid, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS)


def _protected_store(tmp_path, *, protected=True, anchors=True, indexed=True, compressed=False):
    """A synthetic agent-memory store shaped like the real one. The artifact marks protection via the
    `protected:` frontmatter key ONLY (no `type: constraint`), so flipping that single key genuinely
    unprotects it — the real artifact carries both markers, which only makes it harder to unprotect.

    `compressed=True` writes the anchors as a bare keyword list: every anchor still present, marker
    still on, still indexed — the D12 tier reduced to keywords by a consolidation pass."""
    store = tmp_path / "agent-memory"
    store.mkdir(exist_ok=True)
    if not anchors:
        body = "anchors edited out\n"
    elif compressed:
        body = "\n".join("- " + anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS)
    else:
        body = _prose_body()
    (store / "protected-constraints.md").write_text(
        "---\nname: protected-constraints\ndescription: pinned safety tier\n"
        "metadata:\n  node_type: memory\n  protected: " + ("true" if protected else "false")
        + "\n---\n" + body + "\n", encoding="utf-8")
    line = ("- [Protected constraints](protected-constraints.md) - pinned safety tier (D12)\n"
            if indexed else "- [Other fact](other-fact.md) - something else\n")
    (store / "MEMORY.md").write_text("# Memory Index\n\n" + line, encoding="utf-8")
    return str(store)


def _write_guards(root, *, gut=None, drop=None, skip=None, commented=None):
    """Create every guard file with a real assertion, optionally gutting/dropping/disabling one.

    ``skip`` and ``commented`` are the two shapes the old substring check could not see: a file whose
    text still contains "assert" while nothing in it ever runs."""
    gut, drop = gut or set(), drop or set()
    skip, commented = skip or set(), commented or set()
    for rel in SC.GUARD_FILES:
        p = os.path.join(root, rel)
        if rel in drop:
            if os.path.exists(p):
                os.remove(p)                     # ensure absent (a prior call may have created it)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if rel in skip:
            body = ('import pytest\npytestmark = pytest.mark.skip("disabled")\n'
                    "def test_x():\n    assert False\n")
        elif rel in commented:
            body = "def test_x():\n    # assert something here one day\n    pass\n"
        elif rel in gut:
            body = "def test_x():\n    pass\n"
        else:
            body = "def test_x():\n    assert True\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)


# --- individual checks -------------------------------------------------------------------------

def test_scorecard_substrate_states(tmp_path):
    root = str(tmp_path)
    q = _quality_dir(root)
    # missing -> RED
    assert SC.check_scorecard_substrate(root)["status"] == SC.RED
    # present + empty -> GREEN, honest about 0 entries
    open(os.path.join(q, "scorecard.jsonl"), "w").close()
    c = SC.check_scorecard_substrate(root)
    assert c["status"] == SC.GREEN and "0 entries" in c["detail"]
    # present + rows -> GREEN with count
    with open(os.path.join(q, "scorecard.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"a":1}\n{"a":2}\n')
    assert "2 verdict row" in SC.check_scorecard_substrate(root)["detail"]


def test_pir_substrate_counts_only_real_toward_floor(tmp_path):
    """The D11 floor is REAL-only: a surrogate (fault-injected) row populates the descriptive gap but must
    NOT read as tune-eligible, while a REAL alias (`pir`) does — and the readout normalizes via the same
    `_norm_source` the gate uses, so the health line can never drift from the gate it reports on."""
    root = str(tmp_path)
    q = _quality_dir(root)
    with open(os.path.join(q, "pir_outcomes.jsonl"), "w", encoding="utf-8") as f:
        f.write('{"source_class":"fault-injected","predicted":"READY","actual":"clean"}\n')
        f.write('{"source_class":"pir","predicted":"READY","actual":"incident"}\n')      # alias -> REAL
    c = SC.check_pir_substrate(root)
    assert c["status"] == SC.GREEN
    assert "2 labeled outcome(s), 1 REAL" in c["detail"]      # surrogate excluded; alias normalized to REAL


def test_guards_nonvacuous_detects_missing_and_gutted(tmp_path):
    root = str(tmp_path)
    _write_guards(root)
    assert SC.check_guards_nonvacuous(root)["status"] == SC.GREEN
    # a guard with no assertion -> RED (non-vacuity: a skipped/gutted test is red)
    _write_guards(root, gut={"tests/test_scorecard.py"})
    c = SC.check_guards_nonvacuous(root)
    assert c["status"] == SC.RED and "no live assertions" in c["detail"]
    # a deleted guard -> RED
    _write_guards(root, drop={"tests/test_council.py"})
    c2 = SC.check_guards_nonvacuous(root)
    assert c2["status"] == SC.RED and "missing" in c2["detail"]
    # A guard SKIPPED at module level -> RED. The file is present, parses, and its text still
    # contains "assert" — which is exactly why the old substring check reported GREEN for it. With
    # every guard in this shape the whole roster is disabled and the nightly self-check led the
    # morning briefing all-green; this module's docstring already said a skipped test is RED.
    _write_guards(root, skip={"tests/test_memory_guard.py"})
    c3 = SC.check_guards_nonvacuous(root)
    assert c3["status"] == SC.RED and "skipped at module level" in c3["detail"]
    # An assertion that exists only in a COMMENT -> RED, same reason.
    _write_guards(root, commented={"tests/test_ssot_registry.py"})
    c4 = SC.check_guards_nonvacuous(root)
    assert c4["status"] == SC.RED and "no live assertions" in c4["detail"]
    # ...and the whole roster in each disabled shape is RED, not just one file.
    _write_guards(root, skip=set(SC.GUARD_FILES))
    assert SC.check_guards_nonvacuous(root)["status"] == SC.RED


def test_graph_fresh_stale_absent(tmp_path, monkeypatch):
    root = str(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (tmp_path / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline"],
        cwd=root,
        check=True,
    )
    gdir = os.path.join(root, "graphify-out")
    os.makedirs(gdir)
    gpath = os.path.join(gdir, "graph.json")
    open(gpath, "w").close()
    report_path = os.path.join(gdir, "GRAPH_REPORT.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("# Graph report\n")
    mtime = os.path.getmtime(gpath)
    unreceipted = SC.check_graph_fresh(root, now=mtime + 3600)
    assert unreceipted["status"] == SC.UNKNOWN
    assert "refresh evidence is not established" in unreceipted["detail"]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    valid_graph = json.dumps(
        {"built_at_commit": head, "nodes": [], "links": []}, separators=(",", ":")
    ) + "\n"
    with open(gpath, "w", encoding="utf-8") as handle:
        handle.write(valid_graph)
    valid_report = f"# Graph report\n\n- Built from commit: `{head[:8]}`\n"
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(valid_report)
    receipt_path = os.path.join(gdir, ".guarded_refresh.json")
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump({
            "contract": SC.GRAPHIFY_REFRESH_RECEIPT_CONTRACT,
            "graph": SC._stable_graph_identity(gpath),
            "guard": {**SC.GRAPHIFY_GUARD_IDENTITY, "python": "3.12.9"},
            "head": head,
            "phase": "complete",
            "report": SC._stable_report_identity(report_path),
            "root": os.path.realpath(root),
            "state": "clean",
            "updated_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
        }, handle)
    current = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert current["status"] == SC.GREEN and current["name"] == "graph_refresh_receipt"
    assert "completed at this clean HEAD; graph/report bytes still match" in current["detail"]

    real_index_scope = SC._git_index_scope
    monkeypatch.setattr(SC, "_git_index_scope", lambda _root: ("", True))
    uninitialized_submodule = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert uninitialized_submodule["status"] == SC.UNKNOWN
    assert "submodules are unsupported" in uninitialized_submodule["detail"]
    monkeypatch.setattr(SC, "_git_index_scope", real_index_scope)

    receipt_alias = receipt_path + ".alias"
    os.link(receipt_path, receipt_alias)
    hardlinked = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert hardlinked["status"] == SC.UNKNOWN
    assert "singly-linked regular file" in hardlinked["detail"]
    os.remove(receipt_alias)

    other = tmp_path.parent / (tmp_path.name + "-redirect")
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    (other / "other.txt").write_text("other\n", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=other, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "other"],
        cwd=other,
        check=True,
    )
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    redirected = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert redirected["status"] == SC.GREEN, "ambient Git redirection must not change the checked root"

    with open(report_path, "a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    report_replaced = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert report_replaced["status"] == SC.UNKNOWN
    assert "identity/state mismatch" in report_replaced["detail"]
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(valid_report)

    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("# Graph report\n\n- Built from commit: `bbbbbbbb`\n")
    with open(receipt_path, encoding="utf-8") as handle:
        rechained = json.load(handle)
    rechained["report"] = SC._stable_report_identity(report_path)
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(rechained, handle)
    wrong_stamp = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert wrong_stamp["status"] == SC.UNKNOWN
    assert "identity/state mismatch" in wrong_stamp["detail"]
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(valid_report)
    rechained["report"] = SC._stable_report_identity(report_path)
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(rechained, handle)

    for malformed_graph in (
        json.dumps({"built_at_commit": "b" * 40, "nodes": [], "links": []}) + "\n",
        '{"built_at_commit":"' + head + '","built_at_commit":"' + head + '","nodes":[],"links":[]}\n',
        '{"nodes":[],"links":[]}\n',
    ):
        with open(gpath, "w", encoding="utf-8") as handle:
            handle.write(malformed_graph)
        with open(receipt_path, encoding="utf-8") as handle:
            rechained_graph = json.load(handle)
        rechained_graph["graph"] = SC._stable_graph_identity(gpath)
        with open(receipt_path, "w", encoding="utf-8") as handle:
            json.dump(rechained_graph, handle)
        invalid_graph = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
        assert invalid_graph["status"] == SC.UNKNOWN
        assert "guarded refresh receipt invalid" in invalid_graph["detail"]
    with open(gpath, "w", encoding="utf-8") as handle:
        handle.write(valid_graph)
    rechained["graph"] = SC._stable_graph_identity(gpath)
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(rechained, handle)

    real_json_loads = SC.json.loads

    def recurse_on_graph(payload, *args, **kwargs):
        if (
            isinstance(payload, str) and '"built_at_commit"' in payload
        ) or (
            isinstance(payload, (bytes, bytearray)) and b'"built_at_commit"' in payload
        ):
            raise RecursionError("synthetic deeply nested graph")
        return real_json_loads(payload, *args, **kwargs)

    monkeypatch.setattr(SC.json, "loads", recurse_on_graph)
    recursive_graph = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert recursive_graph["status"] == SC.UNKNOWN
    assert "synthetic deeply nested graph" in recursive_graph["detail"]
    monkeypatch.setattr(SC.json, "loads", real_json_loads)

    with open(gpath, "w", encoding="utf-8") as handle:
        handle.write('{"replaced":true}\n')
    replaced = SC.check_graph_fresh(root, now=mtime + 100 * 86400)
    assert replaced["status"] == SC.UNKNOWN
    assert "valid full commit stamp" in replaced["detail"]
    os.remove(gpath)
    assert SC.check_graph_fresh(root, now=mtime)["status"] == SC.UNKNOWN               # absent -> UNKNOWN, not GREEN


def test_stable_receipt_read_rejects_a_named_path_replacement(tmp_path, monkeypatch):
    receipt = tmp_path / ".guarded_refresh.json"
    replacement = tmp_path / "replacement.json"
    receipt.write_bytes(b'{"phase":"complete"}\n')
    replacement.write_bytes(b'{"phase":"pending"}\n')
    real_stat = SC.os.stat
    swapped = False

    def swap_before_named_stat(path, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and os.path.normcase(os.fspath(path)) == os.path.normcase(str(receipt))
            and kwargs.get("follow_symlinks") is False
        ):
            swapped = True
            os.replace(replacement, receipt)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(SC.os, "stat", swap_before_named_stat)
    with pytest.raises(ValueError, match="changed while hashing"):
        SC._stable_file_payload(
            str(receipt), label="guarded refresh receipt", maximum_bytes=16_384
        )


def test_graph_selfchecks_reject_an_indirected_output_root(tmp_path):
    root = tmp_path / "repo"
    external = tmp_path / "external-output"
    root.mkdir()
    external.mkdir()
    output = root / "graphify-out"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(output), str(external)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        output.symlink_to(external, target_is_directory=True)
    try:
        (external / "graph.json").write_text("{}\n", encoding="utf-8")
        fresh = SC.check_graph_fresh(str(root), now=1.0)
        commit = SC.check_graph_commit_current(str(root))
        assert fresh["status"] == SC.UNKNOWN and "path invalid" in fresh["detail"]
        assert commit["status"] == SC.UNKNOWN and "path invalid" in commit["detail"]
    finally:
        if os.name == "nt":
            os.rmdir(output)
        else:
            output.unlink()


def test_graph_selfchecks_reject_a_redirected_git_common_directory(tmp_path):
    root = _healthy_root(tmp_path, None)
    external = tmp_path.parent / (tmp_path.name + "-external-common")
    external.mkdir()
    with open(os.path.join(root, ".git", "commondir"), "w", encoding="utf-8") as handle:
        handle.write(str(external))

    fresh = SC.check_graph_fresh(root, now=1.0)
    commit = SC.check_graph_commit_current(root)
    assert fresh["status"] == SC.UNKNOWN
    assert "common directory is indirected" in fresh["detail"]
    assert commit["status"] == SC.UNKNOWN


def test_selfcheck_git_runner_excludes_repo_local_executable_lookup(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    subprocess.run([real_git, "init", "-q"], cwd=root, check=True)
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run([real_git, "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(
        [
            real_git,
            "-c",
            "user.email=t@e.st",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    fake_root = tmp_path / "fake-root"
    fake_root.mkdir()
    fake = root / ("git.cmd" if os.name == "nt" else "git")
    fake.write_text(
        (
            f"@echo {fake_root}\n@exit /b 0\n"
            if os.name == "nt"
            else f"#!/bin/sh\necho {fake_root}\nexit 0\n"
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    external_fake = fake_root / ("git.cmd" if os.name == "nt" else "git")
    external_fake.write_text(fake.read_text(encoding="utf-8"), encoding="utf-8")
    external_fake.chmod(0o755)
    monkeypatch.setenv(
        "PATH", os.pathsep.join((str(root), str(os.path.dirname(real_git))))
    )

    result = SC._run_git(str(root), "rev-parse", "--verify", "HEAD")
    assert result is not None and result.returncode == 0
    assert os.path.normcase(os.path.realpath(result.args[0])) == os.path.normcase(
        os.path.realpath(real_git)
    )
    monkeypatch.chdir(root)
    assert os.path.normcase(SC._repo_root(None)) == os.path.normcase(str(root.resolve()))
    monkeypatch.chdir(fake_root)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    if os.name == "nt":
        assert os.path.normcase(os.path.realpath(shutil.which("git") or "")) == os.path.normcase(
            os.path.realpath(external_fake)
        )
    external_cwd_result = SC._run_git(
        str(root), "rev-parse", "--verify", "HEAD"
    )
    assert external_cwd_result is not None and external_cwd_result.returncode == 0
    assert os.path.normcase(os.path.realpath(external_cwd_result.args[0])) == os.path.normcase(
        os.path.realpath(real_git)
    )


def test_graph_commit_verdict_pure():
    """The topology stamp never fabricates a refresh verdict from repository drift."""
    V = SC._graph_commit_verdict
    assert V("a" * 40, "a" * 40, None, 0)[0] == SC.GREEN
    assert V("abc1234", "abc1234ff", None, 0)[0] == SC.UNKNOWN
    tree_equivalent = V("a" * 40, "b" * 40, True, 0)
    assert tree_equivalent[0] == SC.UNKNOWN and "tree-equivalent" in tree_equivalent[1]
    drift = V("a" * 40, "b" * 40, True, 5)
    assert drift[0] == SC.UNKNOWN and "not current" in drift[1]
    rewritten = V("a" * 40, "b" * 40, False, 0)
    assert rewritten[0] == SC.UNKNOWN and SC.GRAPHIFY_REFRESH_COMMAND in rewritten[1]
    assert V("a" * 40, "b" * 40, None, 0)[0] == SC.UNKNOWN       # ancestry unknown -> UNKNOWN
    assert V("a" * 40, "b" * 40, True, None)[0] == SC.UNKNOWN    # diff denominator unavailable


def test_graph_commit_counts_non_python_corpus_changes(tmp_path):
    """JSON/config drift is graph drift too; the old .py-only denominator falsely read GREEN."""
    root = str(tmp_path)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    (tmp_path / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    git("add", "baseline.txt")
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline")
    built = git("rev-parse", "HEAD")
    (tmp_path / "tsconfig.JSON").write_text('{"required":["not-extends"]}\n', encoding="utf-8")
    git("add", "tsconfig.JSON")
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "config")
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text(
        json.dumps({"built_at_commit": built, "nodes": [], "links": []}),
        encoding="utf-8",
    )

    result = SC.check_graph_commit_current(root)

    assert result["status"] == SC.UNKNOWN
    assert "1 tracked path(s)" in result["detail"]
    assert "graph commit stamp is not current" in result["detail"]


def test_graph_commit_diff_failure_is_unknown_not_false_green(tmp_path, monkeypatch):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text(
        json.dumps({"built_at_commit": "a" * 40, "nodes": [], "links": []}),
        encoding="utf-8",
    )

    def fake_git(_root, *args):
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="b" * 40 + "\n", stderr="")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(args, 2, stdout="", stderr="denied")
        raise AssertionError(args)

    monkeypatch.setattr(SC, "_run_git", fake_git)

    result = SC.check_graph_commit_current(str(tmp_path))

    assert result["status"] == SC.UNKNOWN
    assert "changed-path denominator" in result["detail"]


def test_graph_commit_absent_and_invalid(tmp_path):
    """The I/O UNKNOWN paths (no git needed): absent graph, unreadable graph, missing stamp -> UNKNOWN."""
    root = str(tmp_path)
    assert SC.check_graph_commit_current(root)["status"] == SC.UNKNOWN          # no graphify-out at all
    gdir = os.path.join(root, "graphify-out")
    os.makedirs(gdir)
    open(os.path.join(gdir, "graph.json"), "w").close()                         # empty -> invalid JSON
    assert SC.check_graph_commit_current(root)["status"] == SC.UNKNOWN
    with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": []}, f)                                             # valid JSON, no built_at_commit
    assert SC.check_graph_commit_current(root)["status"] == SC.UNKNOWN


def test_learnings_discipline(tmp_path):
    root = str(tmp_path)
    q = _quality_dir(root)
    # missing -> RED
    assert SC.check_learnings_discipline(root)["status"] == SC.RED
    # the real file -> GREEN (test_learnings.py keeps it disciplined)
    import shutil
    shutil.copyfile(_REAL_LEARNINGS, os.path.join(q, "learnings.md"))
    assert SC.check_learnings_discipline(root)["status"] == SC.GREEN
    # a clearly-violating file (over-length + uncited + coasting) -> RED
    with open(os.path.join(q, "learnings.md"), "w", encoding="utf-8") as f:
        f.write("\n".join("- unverified claim of great progress" for _ in range(150)))
    assert SC.check_learnings_discipline(root)["status"] == SC.RED


# --- the GUARD_FILES exact-membership pin (P0-6 / DEC-004; gap G-006) ----------------------------

def test_guard_files_exact_pin():
    """THE roster pin: check_guards_nonvacuous only watches what GUARD_FILES lists, so before P0-6
    dropping an entry TOGETHER with its file left every check green — the one silent way to un-guard
    a guard. This pin makes the roster membership itself the fact under test: exact and
    duplicate-free. Editing the roster now means editing this pin in the same reviewed change.
    (Count note: the P0-6 plan said 13→14, but the roster already held 14 when P0-5 added
    test_registry_freshness.py in the same window the plan was written — the in-code owner wins,
    so with test_version.py the true membership is 15.)"""
    expected = {
        "tests/test_memory_guard.py", "tests/test_learnings.py", "tests/test_scorecard.py",
        "tests/test_calibration.py", "tests/test_clock.py", "tests/test_domain_packs.py",
        "tests/test_council.py", "tests/test_eval_harness.py", "tests/test_ssot_registry.py",
        "tests/test_pipeline_golden.py", "tests/test_defect_panel.py", "tests/test_fault_corpus.py",
        "tests/test_ollama_judge.py", "tests/test_registry_freshness.py",
        # P0-6 / G-006: the schema-version VALUE pin joins the roster
        "tests/test_version.py",
    }
    assert set(SC.GUARD_FILES) == expected
    assert len(SC.GUARD_FILES) == len(expected) == 15     # no duplicate hiding a dropped entry


def test_guard_files_exist_and_assert_in_this_repo():
    """Non-vacuity against the REAL repo (every other case here uses synthetic roots): each pinned
    guard file exists HERE and asserts. This is what turns 'dropped the roster entry AND deleted the
    file' into a pytest failure instead of a silently green selfcheck."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    c = SC.check_guards_nonvacuous(repo)
    assert c["status"] == SC.GREEN, c["detail"]


# --- judge trust: the PROVISIONAL-verdict consumer (P0-6 / DEC-004; gap G-006) -------------------

def _scorecard_with(root, rows):
    q = _quality_dir(root)
    with open(os.path.join(q, "scorecard.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_judge_trust_missing_scorecard_is_signal_absent(tmp_path):
    c = SC.check_judge_trust(str(tmp_path))
    assert c["status"] == SC.UNKNOWN and "signal_absent" in c["detail"]


def test_judge_trust_advisory_approvals_green_with_demotion_disclosed(tmp_path):
    """An honestly-marked weak judge (TNR 0.2 < floor) is a healthy instrument reading: GREEN, with
    the demotion disclosed — every judge APPROVE counted advisory, none gating."""
    root = str(tmp_path)
    _scorecard_with(root, [
        {"date": "2026-07-08", "deliverable": "judge-baseline", "score": None, "verdict": None,
         "judge_tnr": 0.2},
        {"date": "2026-07-09", "deliverable": "set", "score": None, "verdict": "APPROVE",
         "judge_tnr": 0.2, "provisional": True},
    ])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.GREEN
    assert "1/1" in c["detail"] and "BELOW the floor" in c["detail"]


def test_judge_trust_fabricated_confidence_goes_red(tmp_path):
    """THE enforcement teeth: an APPROVE persisted provisional=false while its judge_tnr is
    null/below the floor is fabricated confidence — RED, the exact drift this consumer exists to
    catch (any code gating on verdicts would have trusted it)."""
    root = str(tmp_path)
    _scorecard_with(root, [{"date": "2026-07-09", "deliverable": "set", "score": None,
                            "verdict": "APPROVE", "judge_tnr": None, "provisional": False}])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.RED and "fabricated confidence" in c["detail"]


def test_judge_trust_floor_clearing_baseline_gates(tmp_path):
    root = str(tmp_path)
    _scorecard_with(root, [
        {"date": "2026-07-10", "deliverable": "judge-baseline", "score": None, "verdict": None,
         "judge_tnr": 0.6},
        {"date": "2026-07-10", "deliverable": "set", "score": None, "verdict": "APPROVE",
         "judge_tnr": 0.6, "provisional": False},
    ])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.GREEN and "clears the floor" in c["detail"] and "0/1" in c["detail"]


def test_judge_trust_null_trust_latest_baseline_reports_demotion(tmp_path):
    """P1-3/DEC-004: when the LATEST baseline is a null-trust measurement (the specificity
    fail-safe), the check must report the demotion — not crash on None-vs-float and not fall back
    to an older flattering number."""
    root = str(tmp_path)
    _scorecard_with(root, [
        {"date": "2026-07-10", "deliverable": "judge-baseline", "score": None, "verdict": None,
         "judge_tnr": 0.4},
        {"date": "2026-07-10", "deliverable": "judge-baseline", "score": None, "verdict": None,
         "judge_tnr": None, "notes": "NO SPECIFICITY (rejected the clean control)"},
    ])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.GREEN and "NULL trust" in c["detail"]
    assert "TNR=0.4" not in c["detail"]          # the stale numeric row must not be the report


def test_judge_trust_legacy_unmarked_rows_are_advisory_not_red(tmp_path):
    """Append-only history: a pre-P0-6 APPROVE (no provisional key at all) reads as advisory via the
    predicate — never RED (absent is unmarked, not a lie) and never trusted as gating."""
    root = str(tmp_path)
    _scorecard_with(root, [{"date": "2026-07-07", "deliverable": "set", "score": None,
                            "verdict": "APPROVE"}])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.GREEN
    assert "1/1" in c["detail"] and "no judge-baseline" in c["detail"]


# --- the protected-tier artifact pin (P0-1 / DEC-005; gap G-001, evidence BLK-1) -----------------

def test_protected_artifact_green_when_pinned(tmp_path):
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path))
    assert c["status"] == SC.GREEN and "pinned" in c["detail"]


def test_protected_artifact_frontmatter_flip_goes_red(tmp_path):
    """THE P0-1 acceptance: flipping `protected: true -> false` in the store makes the check RED."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path, protected=False))
    assert c["status"] == SC.RED
    assert "no longer marks the artifact protected" in c["detail"]


def test_protected_artifact_store_absent_is_signal_absent_never_green(tmp_path):
    """THE second P0-1 acceptance: a machine without the store reads explicit signal_absent
    (UNKNOWN) — coverage-honesty forbids rendering an unobserved store as healthy."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=str(tmp_path / "no-such-store"))
    assert c["status"] == SC.UNKNOWN
    assert "signal_absent" in c["detail"]
    assert c["status"] != SC.GREEN


def test_protected_artifact_dropped_artifact_goes_red(tmp_path):
    """Deleting protected-constraints.md from a live store is the exact loss class memory_guard
    names (missing_protected) — RED, never a silent gap."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path)
    os.remove(os.path.join(store, "protected-constraints.md"))
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "dropped" in c["detail"]


def test_protected_artifact_gutted_body_goes_red(tmp_path):
    """Frontmatter intact but the canonical anchors edited out of the body — drift, not deletion —
    must still be RED (unpinned_constraints is the detector)."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path, anchors=False))
    assert c["status"] == SC.RED and "unpinned" in c["detail"]


def test_protected_artifact_compressed_to_a_keyword_list_goes_red(tmp_path):
    """THE D12 verbatim floor. The artifact exists, still marks itself protected, still contains
    every canonical anchor and is still indexed in MEMORY.md — and has been compressed to a bullet
    list of the anchors, which is exactly what the never-compressible tier forbids. Every existing
    sub-check passes on that shape, so before the floor this read GREEN ("all 8 canonical anchors
    pinned") over a compressed safety tier."""
    root = _doctrine_root(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=_protected_store(tmp_path, compressed=True))
    assert c["status"] == SC.RED, c["detail"]
    assert "COMPRESSED" in c["detail"] or "bare keyword" in c["detail"]


def test_protected_body_integrity_measures_both_floors():
    """The pure decision (no I/O): a keyword list trips both floors, a bare-anchor bullet trips the
    context floor even inside a long entry, and doctrine prose trips neither. An anchor that is
    ABSENT is not this function's loss class (memory_guard.unpinned_constraints owns it)."""
    cons = MG.CANONICAL_SAFETY_CONSTRAINTS
    keyword_list = "\n".join("- " + a for _, a in cons)
    probs = SC.protected_body_integrity(keyword_list, cons)
    assert probs and any("COMPRESSED" in p for p in probs)
    assert any("bare keyword" in p for p in probs)
    assert SC.protected_body_integrity(_prose_body(), cons) == []
    # padded to clear the volume floor, but each anchor still stands alone -> still caught
    padded = keyword_list + "\n" + ("filler prose about the engagement. " * 60)
    assert any("bare keyword" in p for p in SC.protected_body_integrity(padded, cons))
    # an absent anchor is NOT reported here (no occurrence -> no context claim to make)
    assert SC.protected_body_integrity("", cons) != []          # empty body still trips volume
    assert not any("bare keyword" in p for p in SC.protected_body_integrity("", cons))


def test_protected_artifact_index_prune_goes_red(tmp_path):
    """BLK-1 route (d): a MEMORY.md prune that drops the index line orphans the fact from
    session-start re-surfacing — RED; a missing index entirely is the same loss class."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path, indexed=False)
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "no longer indexes" in c["detail"]
    os.remove(os.path.join(store, "MEMORY.md"))
    c2 = SC.check_protected_artifact(root, memory_dir=store)
    assert c2["status"] == SC.RED and "index absent" in c2["detail"]


def test_protected_artifact_doctrine_drift_goes_red(tmp_path):
    """An anchor no longer verbatim in CLAUDE.md (the doctrine owner) is drift (reconcile_constraints)
    — RED even with an intact store; and verified drift outranks an absent store's UNKNOWN."""
    root = str(tmp_path)
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(anchor for _, anchor in MG.CANONICAL_SAFETY_CONSTRAINTS[1:]))  # 1st anchor gone
    store = _protected_store(tmp_path)
    c = SC.check_protected_artifact(root, memory_dir=store)
    assert c["status"] == SC.RED and "doctrine drift" in c["detail"]
    c2 = SC.check_protected_artifact(root, memory_dir=str(tmp_path / "no-such-store"))
    assert c2["status"] == SC.RED and "absent" in c2["detail"]


def test_protected_artifact_env_var_points_the_store(tmp_path, monkeypatch):
    """The DEC-005 portability contract: $AGENT_MEMORY_DIR relocates the store; an explicit argument
    beats the env; without either, THIS test never resolves to the per-machine default."""
    root = _doctrine_root(tmp_path)
    store = _protected_store(tmp_path)
    monkeypatch.setenv(MG.AGENT_MEMORY_DIR_ENV, store)
    assert SC.check_protected_artifact(root)["status"] == SC.GREEN
    monkeypatch.setenv(MG.AGENT_MEMORY_DIR_ENV, str(tmp_path / "relocated-away"))
    assert SC.check_protected_artifact(root, memory_dir=store)["status"] == SC.GREEN   # arg > env
    assert SC.check_protected_artifact(root)["status"] == SC.UNKNOWN                   # env honored


# --- the aggregate ------------------------------------------------------------------------------

def _init_git_with_current_graph(root):
    """Make ``root`` a git repo with one commit and stamp graphify-out/graph.json's ``built_at_commit``
    to HEAD, so :func:`check_graph_commit_current` reads GREEN 'current' — a healthy system IS a real
    git checkout with a code-current graph (that is what the aggregate all-green test now asserts)."""
    import subprocess

    def _g(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)
    _g("init", "-q")
    _g("add", "-A")
    _g("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "fixture", "--no-gpg-sign")
    head = _g("rev-parse", "HEAD").stdout.strip() or ("0" * 40)
    with open(os.path.join(root, "graphify-out", "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"built_at_commit": head, "nodes": [], "links": []}, f)
    with open(os.path.join(root, "graphify-out", "GRAPH_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(f"# Graph report\n\n- Built from commit: `{head[:8]}`\n")


def _healthy_root(tmp_path, now_ref):
    root = _doctrine_root(tmp_path)                 # CLAUDE.md doctrine for the protected reconcile
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("graphify-out/\nagent-memory/\n")
    q = _quality_dir(root)
    for name in ("scorecard.jsonl", "pir_outcomes.jsonl", "nightly_runs.jsonl"):
        open(os.path.join(q, name), "w").close()
    import shutil
    shutil.copyfile(_REAL_LEARNINGS, os.path.join(q, "learnings.md"))
    _write_guards(root)
    os.makedirs(os.path.join(root, "graphify-out"))
    _init_git_with_current_graph(root)              # HEAD + a current graph.json (writes graphify-out/graph.json)
    gpath = os.path.join(root, "graphify-out", "graph.json")
    report_path = os.path.join(root, "graphify-out", "GRAPH_REPORT.md")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    with open(os.path.join(root, "graphify-out", ".guarded_refresh.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "contract": SC.GRAPHIFY_REFRESH_RECEIPT_CONTRACT,
            "graph": SC._stable_graph_identity(gpath),
            "guard": {**SC.GRAPHIFY_GUARD_IDENTITY, "python": "3.12.9"},
            "head": head,
            "phase": "complete",
            "report": SC._stable_report_identity(report_path),
            "root": os.path.realpath(root),
            "state": "clean",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, handle)
    return root


def test_graph_fresh_binds_the_exact_worktree_despite_core_worktree_redirect(
    tmp_path
):
    root = _healthy_root(tmp_path, None)
    external = tmp_path.parent / (tmp_path.name + "-external-worktree")
    shutil.copytree(root, external, ignore=shutil.ignore_patterns(".git"))
    subprocess.run(
        ["git", "-C", root, "config", "core.worktree", str(external)], check=True
    )
    claude = os.path.join(root, "CLAUDE.md")
    with open(claude, "a", encoding="utf-8") as handle:
        handle.write("dirty root only\n")
    redirected = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert redirected.stdout == ""

    result = SC.check_graph_fresh(root, now=1.0)
    assert result["status"] == SC.UNKNOWN
    assert "identity/state mismatch" in result["detail"]


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_graph_fresh_rejects_index_flags_that_hide_tracked_changes(
    tmp_path, flag
):
    root = _healthy_root(tmp_path, None)
    subprocess.run(
        ["git", "-C", root, "update-index", flag, "CLAUDE.md"], check=True
    )
    with open(os.path.join(root, "CLAUDE.md"), "a", encoding="utf-8") as handle:
        handle.write("hidden dirty root\n")
    hidden = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert hidden.stdout == ""

    result = SC.check_graph_fresh(root, now=1.0)
    assert result["status"] == SC.UNKNOWN
    assert "hidden or unreadable state flags" in result["detail"]


def test_graph_fresh_disables_fsmonitor_valid_shortcuts(tmp_path):
    root = _healthy_root(tmp_path, None)
    subprocess.run(
        ["git", "-C", root, "config", "core.fsmonitor", "true"], check=True
    )
    subprocess.run(
        ["git", "-C", root, "update-index", "--fsmonitor"], check=True
    )
    subprocess.run(
        ["git", "-C", root, "update-index", "--untracked-cache"], check=True
    )
    subprocess.run(
        ["git", "-C", root, "update-index", "--fsmonitor-valid", "CLAUDE.md"],
        check=True,
    )
    tagged = subprocess.run(
        ["git", "-C", root, "ls-files", "-f", "CLAUDE.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert tagged.stdout.startswith("h ")
    index_path = os.path.join(root, ".git", "index")
    with open(index_path, "rb") as handle:
        index_before = handle.read()
    index_mtime = os.stat(index_path).st_mtime_ns
    with open(os.path.join(root, "CLAUDE.md"), "a", encoding="utf-8") as handle:
        handle.write("fsmonitor-hidden change\n")
    result = SC.check_graph_fresh(root, now=1.0)
    assert result["status"] == SC.UNKNOWN
    assert "identity/state mismatch" in result["detail"]
    with open(index_path, "rb") as handle:
        assert handle.read() == index_before
    assert os.stat(index_path).st_mtime_ns == index_mtime


def test_graph_fresh_never_executes_a_configured_fsmonitor_command(tmp_path):
    root = _healthy_root(tmp_path, None)
    sentinel = tmp_path.parent / (tmp_path.name + "-fsmonitor-invoked.txt")
    command = tmp_path.parent / (tmp_path.name + "-fsm.sh")
    command.write_text(
        f'#!/bin/sh\necho invoked >> "{sentinel.as_posix()}"\necho token\nexit 0\n',
        encoding="utf-8",
    )
    command.chmod(0o755)
    subprocess.run(
        ["git", "-C", root, "config", "core.fsmonitor", command.as_posix()], check=True
    )
    subprocess.run(
        ["git", "-C", root, "update-index", "--fsmonitor"], check=True
    )
    sentinel.unlink(missing_ok=True)
    subprocess.run(
        ["git", "-C", root, "ls-files", "-t", "CLAUDE.md"], check=True
    )
    assert sentinel.exists(), "positive control: plain Git must invoke the configured monitor"
    sentinel.unlink()

    result = SC.check_graph_fresh(root, now=1.0)
    assert result["status"] == SC.GREEN
    assert not sentinel.exists()


def test_graph_fresh_rejects_active_filters_without_executing_them(tmp_path):
    root = _healthy_root(tmp_path, None)
    sentinel = tmp_path.parent / (tmp_path.name + "-filter-invoked.txt")
    command = tmp_path.parent / (tmp_path.name + "-filter.sh")
    command.write_text(
        f'#!/bin/sh\necho invoked >> "{sentinel.as_posix()}"\ncat\n',
        encoding="utf-8",
    )
    command.chmod(0o755)
    subprocess.run(
        [
            "git",
            "-C",
            root,
            "config",
            "filter.selfcheck-test.clean",
            command.as_posix(),
        ],
        check=True,
    )
    with open(os.path.join(root, ".git", "info", "attributes"), "w", encoding="utf-8") as handle:
        handle.write("*.md filter=selfcheck-test\n")
    sentinel.unlink(missing_ok=True)
    with open(os.path.join(root, "CLAUDE.md"), "a", encoding="utf-8") as handle:
        handle.write("filter-triggering change\n")
    subprocess.run(
        ["git", "-C", root, "diff", "--", "CLAUDE.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert sentinel.exists(), "positive control: plain Git must invoke the configured filter"
    sentinel.unlink()

    result = SC.check_graph_fresh(root, now=1.0)
    assert result["status"] == SC.UNKNOWN
    assert "filter state is active" in result["detail"]
    assert not sentinel.exists()


def test_run_selfcheck_all_green(tmp_path):
    root = _healthy_root(tmp_path, None)
    gpath = os.path.join(root, "graphify-out", "graph.json")
    rep = SC.run_selfcheck(root, now=os.path.getmtime(gpath) + 3600,
                           memory_dir=_protected_store(tmp_path))
    assert rep["verdict"] == "GREEN" and rep["summary"]["red"] == 0 and rep["summary"]["unknown"] == 0


def test_run_selfcheck_absent_graph_is_green_with_gaps(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "graphify-out", "graph.json"))     # worktree: no graph
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    # both graph checks (mtime freshness AND commit currency) go UNKNOWN when the graph is absent
    assert rep["verdict"] == "GREEN-with-gaps" and rep["summary"]["unknown"] == 2
    assert rep["summary"]["red"] == 0                                # unknown is disclosed, not counted red


def test_run_selfcheck_absent_store_is_green_with_gaps_not_green(tmp_path):
    """The P0-1 aggregate acceptance: an otherwise-healthy system with no reachable agent-memory
    store must disclose the gap (signal_absent -> GREEN-with-gaps), never render plain GREEN."""
    root = _healthy_root(tmp_path, None)
    gpath = os.path.join(root, "graphify-out", "graph.json")
    rep = SC.run_selfcheck(root, now=os.path.getmtime(gpath) + 3600,
                           memory_dir=str(tmp_path / "no-such-store"))
    assert rep["verdict"] == "GREEN-with-gaps" and rep["summary"]["red"] == 0
    byname = {c["name"]: c for c in rep["checks"]}
    assert byname["protected_artifact"]["status"] == SC.UNKNOWN
    assert "signal_absent" in byname["protected_artifact"]["detail"]


def test_run_selfcheck_survives_an_undecodable_substrate_file(tmp_path):
    """The module docstring's promise — "a check that raises is caught and reported UNKNOWN, never
    crashes the nightly run" — made mechanical. `run_selfcheck` wrapped nothing and the per-check
    guards caught only OSError, so ONE non-UTF-8 byte in a feedback substrate raised
    UnicodeDecodeError (a ValueError) out of the whole run: the immune system went dark instead of
    reporting that it had gone dark, and the nightly clock/briefing lost every other signal too."""
    root = _healthy_root(tmp_path, None)
    q = os.path.join(root, "docs", "quality")
    for name in ("scorecard.jsonl", "pir_outcomes.jsonl", "nightly_runs.jsonl"):
        with open(os.path.join(q, name), "wb") as f:
            f.write(b'{"date": "2026-07-28"}\n\xff\xfe not utf-8\n')
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    byname = {c["name"]: c for c in rep["checks"]}
    assert len(rep["checks"]) == 9                       # every check still reported
    for name in ("scorecard_substrate", "pir_outcomes_substrate", "nightly_ledger"):
        assert byname[name]["status"] == SC.UNKNOWN, byname[name]
        assert "UnicodeDecodeError" in byname[name]["detail"]
    assert rep["verdict"] != "GREEN"                     # an unevaluated check is never plain green
    assert SC.render(rep)                                # and the report still renders


def test_run_selfcheck_reports_a_raising_check_under_its_own_name(tmp_path, monkeypatch):
    """A check that raises for ANY reason is reported UNKNOWN by name, and the run continues."""
    root = _healthy_root(tmp_path, None)

    def _boom(*_a, **_k):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(SC, "check_guards_nonvacuous", _boom)
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    byname = {c["name"]: c for c in rep["checks"]}
    assert byname["guards_nonvacuous"]["status"] == SC.UNKNOWN
    assert "RuntimeError" in byname["guards_nonvacuous"]["detail"]
    assert byname["scorecard_substrate"]["status"] == SC.GREEN     # the others still ran


def test_judge_trust_discloses_unauthenticated_score_exemption(tmp_path):
    """A scored APPROVE is exempt from the TNR floor as "deterministic harness output" — a claim the
    row schema cannot authenticate. The exemption must be DISCLOSED, not silently absorb the row out
    of the denominator; and a row that also carries judge provenance is a judge verdict again, so a
    scored, reviewed_by-stamped, below-floor APPROVE persisted provisional=false is still RED."""
    root = str(tmp_path)
    _scorecard_with(root, [{"date": "2026-07-28", "deliverable": "golden", "score": 100,
                            "verdict": "APPROVE", "judge_tnr": None, "provisional": False}])
    c = SC.check_judge_trust(root)
    assert c["status"] == SC.GREEN
    assert "1 scored APPROVE row(s) exempt" in c["detail"] and "not authenticated" in c["detail"]
    root2 = str(tmp_path / "r2")
    os.makedirs(root2, exist_ok=True)
    _scorecard_with(root2, [{"date": "2026-07-28", "deliverable": "set", "score": 100,
                             "verdict": "APPROVE", "judge_tnr": 0.2, "provisional": False,
                             "reviewed_by": "deliverable-qa-reviewer"}])
    assert SC.check_judge_trust(root2)["status"] == SC.RED


def test_run_selfcheck_red_leads(tmp_path):
    root = _healthy_root(tmp_path, None)
    os.remove(os.path.join(root, "docs", "quality", "scorecard.jsonl"))   # break one guard
    rep = SC.run_selfcheck(root, now=1.0, memory_dir=_protected_store(tmp_path))
    assert rep["verdict"] == "RED"
    assert rep["leads"] and rep["leads"][0]["name"] == "scorecard_substrate"
    assert "scorecard_substrate" in SC.render(rep)


def test_pir_and_nightly_substrate_are_red_when_missing(tmp_path):
    """Both feedback substrates go RED when their store is absent — absence is a RED signal, not silence."""
    r1 = SC.check_pir_substrate(str(tmp_path))
    assert r1["status"] == SC.RED and "missing" in r1["detail"]
    r2 = SC.check_nightly_ledger(str(tmp_path))
    assert r2["status"] == SC.RED and "missing" in r2["detail"]


def test_main_exit_codes_map_red_to_4_and_clean_to_0(monkeypatch):
    # isolate main's exit-code mapping from render's report shape
    monkeypatch.setattr(SC, "render", lambda r: "")
    monkeypatch.setattr(SC, "run_selfcheck", lambda *a, **k: {"verdict": SC.RED})
    assert SC.main([]) == 4                                   # any RED check -> exit 4
    monkeypatch.setattr(SC, "run_selfcheck", lambda *a, **k: {"verdict": SC.GREEN})
    assert SC.main([]) == 0
