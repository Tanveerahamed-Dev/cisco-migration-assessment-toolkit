"""Refutation controls for the hosted knowledge handoff; no full corpus generation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("knowledge_export", ROOT / ".github/scripts/knowledge_export.py")
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def environment():
    return {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": subject.REPOSITORY,
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}


@pytest.mark.parametrize("key,value", [
    ("GITHUB_ACTIONS", "false"), ("RUNNER_ENVIRONMENT", "self-hosted"),
    ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_REPOSITORY", "someone/else"), ("GITHUB_SHA", "main"),
    ("GITHUB_RUN_ID", "0"), ("GITHUB_RUN_ATTEMPT", "../1"),
])
def test_admission_refuses_foreign_runner_event_or_identity(key, value):
    env = environment()
    subject.admit(env, subject.SOURCE_COMMIT)
    env[key] = value
    with pytest.raises(subject.Refusal):
        subject.admit(env, subject.SOURCE_COMMIT)


@pytest.mark.parametrize("revision", ["main", "a" * 40, subject.SOURCE_COMMIT.upper(), "", "../source"])
def test_source_choice_is_explicit_and_closed(revision):
    with pytest.raises(subject.Refusal, match="unreviewed_source_revision"):
        subject.admit(environment(), revision)


def test_producer_does_not_inherit_credentials_or_external_backend_controls(monkeypatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN",
                "GRAPHIFY_BACKEND", "GIT_CONFIG_COUNT", "PYTHONPATH", "HTTP_PROXY"):
        monkeypatch.setenv(key, "must-not-be-forwarded")
    child = subject.child_environment()
    assert "must-not-be-forwarded" not in child.values()
    assert child["GIT_NO_REPLACE_OBJECTS"] == "1"


@pytest.mark.parametrize("mutation,code", [
    ({"HEAD": "b" * 40}, "source_revision_mismatch"),
    ({"HEAD^{tree}": "c" * 40}, "source_revision_mismatch"),
    ({"status": "?? Handwritten.md"}, "source_checkout_not_clean"),
])
def test_actual_source_identity_rejects_revision_tree_and_dirty_drift(tmp_path, monkeypatch, mutation, code):
    (tmp_path / ".git").mkdir()
    outputs = {"HEAD": subject.SOURCE_COMMIT, "HEAD^{tree}": subject.SOURCE_TREE, "status": ""}

    def fake_git(root, *arguments):
        return outputs["status" if arguments[0] == "status" else arguments[-1]]

    monkeypatch.setattr(subject, "git", fake_git)
    assert subject.source_identity(tmp_path)["commit"] == subject.SOURCE_COMMIT
    outputs.update(mutation)
    with pytest.raises(subject.Refusal, match=code):
        subject.source_identity(tmp_path)


def test_linked_worktree_source_is_refused(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    with pytest.raises(subject.Refusal, match="standalone_source_checkout_required"):
        subject.source_identity(tmp_path)


def graph():
    return {"built_at_commit": subject.SOURCE_COMMIT, "nodes": [{"id": "a", "_origin": "ast"}], "links": []}


@pytest.mark.parametrize("change,code", [
    (lambda g: g.update(built_at_commit="b" * 40), "graph_source_stamp_mismatch"),
    (lambda g: g["nodes"].append(dict(g["nodes"][0])), "graph_identity_invalid"),
    (lambda g: g["nodes"][0].update(_origin="llm"), "non_ast_graph_origin"),
    (lambda g: g["links"].append({"source": "a", "target": "absent"}), "dangling_graph_edge"),
])
def test_graph_refutations_are_nonvacuous(change, code):
    value = graph()
    assert subject.validate_graph(value)["nodes"] == 1
    change(value)
    with pytest.raises(subject.Refusal, match=code):
        subject.validate_graph(value)


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    node_name = "A--" + hashlib.sha256(b"a").hexdigest()[:16]
    (vault / f"{node_name}.md").write_text("# A\n[[Community]]\n", encoding="utf-8")
    (vault / "Community.md").write_text(f"# Community\n[[{node_name}|A]]\n", encoding="utf-8")
    subject.write_json(vault / "graph.canvas", {"nodes": [{"id": "1", "type": "file", "file": f"{node_name}.md"}],
                                               "edges": []})
    graph_raw, labels_raw = subject.canonical(graph()), b"{}"

    def seal():
        members = [row for row in subject.rows(vault) if row["path"] != "atlas-obsidian-receipt.json"]
        subject.write_json(vault / "atlas-obsidian-receipt.json", {
            "graph_sha256": subject.digest(graph_raw), "labels_sha256": subject.digest(labels_raw),
            "node_count": 1, "member_count_excluding_receipt": len(members),
            "member_digest_excluding_receipt": subject.digest(subject.canonical(members)),
            "absolute_root_embedded": False,
        })
    seal()
    return vault, graph_raw, labels_raw, seal


def test_vault_checks_bind_receipt_and_every_link(tmp_path):
    vault, raw, labels, seal = make_vault(tmp_path)
    assert subject.validate_vault(vault, graph(), raw, labels)["wikilinks_checked"] == 2
    (vault / "Community.md").write_text("[[Missing]]", encoding="utf-8")
    with pytest.raises(subject.Refusal, match="vault_receipt_mismatch"):
        subject.validate_vault(vault, graph(), raw, labels)
    seal()  # Even a freshly resealed ledger cannot bless a broken link.
    with pytest.raises(subject.Refusal, match="vault_dangling_wikilink"):
        subject.validate_vault(vault, graph(), raw, labels)


def test_vault_refuses_canvas_escape_and_missing_node_note(tmp_path):
    vault, raw, labels, seal = make_vault(tmp_path)
    subject.write_json(vault / "graph.canvas", {"nodes": [{"id": "x", "type": "file", "file": "../secret.md"}]})
    seal()
    with pytest.raises(subject.Refusal, match="canvas_file_reference_invalid"):
        subject.validate_vault(vault, graph(), raw, labels)
    next(p for p in vault.glob("*.md") if "--" in p.name).rename(vault / "Foreign.md")
    (vault / "Community.md").write_text("# community", encoding="utf-8")
    seal()
    with pytest.raises(subject.Refusal, match="vault_node_identity_coverage"):
        subject.validate_vault(vault, graph(), raw, labels)


def test_report_refusal_never_reaches_export_or_success_manifest(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    identity = {"commit": subject.SOURCE_COMMIT, "tree": subject.SOURCE_TREE, "tracked_status": "clean"}
    monkeypatch.setattr(subject, "source_identity", lambda root: identity)
    phases = []

    def fake_run(root, dest, phase, tool, *args):
        phases.append(phase)
        if phase == "report_audit":
            (dest / "logs/report_audit.txt").write_text('{"status":"block","error_codes":["graph_report_graph_invalid"]}')
            raise subject.Refusal("report_audit_refused")
        if phase.startswith("identity_"):
            return subject.SOURCE_COMMIT + "\tclean\t" + "c" * 64
        return "{}"

    monkeypatch.setattr(subject, "run", fake_run)
    with pytest.raises(subject.Refusal, match="report_audit_refused"):
        subject.generate(source, output, subject.SOURCE_COMMIT)
    assert "full_update" in phases and "receipt_status" in phases
    assert "obsidian_export" not in phases
    assert not (output / "obsidian.zip").exists()
    assert not (output / "knowledge-manifest.json").exists()


def test_local_admission_failure_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    output, diagnostics = tmp_path / "output", tmp_path / "diagnostics"
    assert subject.main(["--source-root", str(tmp_path), "--expected-source-commit", subject.SOURCE_COMMIT,
                         "--output", str(output), "--diagnostics", str(diagnostics)]) == 1
    assert not output.exists() and not diagnostics.exists()


def test_existing_destination_is_preserved_even_for_hosted_admission(tmp_path, monkeypatch):
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "existing-notes"
    output.mkdir()
    note = output / "Handwritten.md"
    note.write_text("keep this note", encoding="utf-8")
    assert subject.main(["--source-root", str(tmp_path / "source"),
                         "--expected-source-commit", subject.SOURCE_COMMIT,
                         "--output", str(output), "--diagnostics", str(output / "diagnostics")]) == 1
    assert note.read_text(encoding="utf-8") == "keep this note"
    assert list(output.iterdir()) == [note]


def test_success_packages_only_after_all_checks_and_binds_zip_bytes(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    identity = {"commit": subject.SOURCE_COMMIT, "tree": subject.SOURCE_TREE, "tracked_status": "clean"}
    monkeypatch.setattr(subject, "source_identity", lambda root: identity)
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    phases = []

    def fake_run(root, dest, phase, tool, *args):
        phases.append(phase)
        if phase == "bootstrap":
            target = root / "graphify-out"
            target.mkdir()
            for member in subject.GRAPH_MEMBERS:
                raw = subject.canonical(graph()) if member == "graph.json" else b"{}"
                (target / member).write_bytes(raw)
        if phase.startswith("identity_"):
            return subject.SOURCE_COMMIT + "\tclean\t" + "c" * 64
        if phase == "report_audit":
            return '{"status":"pass"}'
        if phase == "obsidian_export":
            target = Path(args[args.index("--dir") + 1])
            vault, _, _, _ = make_vault(target.parent)
            vault.rename(target)
        return "{}"

    monkeypatch.setattr(subject, "run", fake_run)
    proof = subject.generate(source, output, subject.SOURCE_COMMIT)
    assert phases.index("report_audit") < phases.index("obsidian_export")
    assert proof["source"] == identity
    assert proof["vault_checks"]["wikilinks_checked"] == 2
    manifest = json.loads((output / "knowledge-manifest.json").read_bytes())
    zipped = next(row for row in manifest["members"] if row["path"] == "obsidian.zip")
    assert zipped["sha256"] == subject.digest((output / "obsidian.zip").read_bytes())
    assert all(row["path"] != "knowledge-manifest.json" for row in manifest["members"])
    with zipfile.ZipFile(output / "obsidian.zip") as archive:
        assert "atlas-obsidian-receipt.json" in archive.namelist()
        assert "graph.canvas" in archive.namelist()
    assert not proof["graph_checks"]["global_corpus_complete"]


def test_report_verifier_budget_is_unchanged():
    text = (ROOT / "tools/verify_graph_report.py").read_text(encoding="utf-8")
    assert "MAX_JSON_VALUES = 2_000_000" in text
    assert "values > MAX_JSON_VALUES" in text


def test_code_spans_are_not_interpreted_as_wikilinks():
    assert list(subject.wiki_targets("`[[code]]`\n```text\n[[fenced]]\n```\n[[Real#part|label]]")) == ["real"]


def test_wikilink_filenames_keep_backticks_while_code_is_excluded():
    name = "4. Keep `compass`'s strategic frame--0123456789abcdef"
    assert list(subject.wiki_targets(f"[[{name}|heading]] `[[ignored]]` [[Missing]]")) == [name.casefold(), "missing"]
    assert list(subject.wiki_targets("````md\n[[ignored]]\n```\n[[still-ignored]]\n````\n[[Real]]")) == ["real"]


@pytest.fixture
def diagnostic():
    spec = importlib.util.spec_from_file_location(
        "knowledge_report_diagnostics", ROOT / ".github/scripts/knowledge_report_diagnostics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_inputs(tmp_path, raw):
    graph_path = tmp_path / "graph.json"
    graph_path.write_bytes(raw)
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("# intentionally unparsed report\n", encoding="utf-8")
    (tmp_path / ".graphify_labels.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".graphify_labels.json.sig").write_text("{}", encoding="utf-8")
    return graph_path, report


@pytest.mark.parametrize("case", ["values", "depth", "malformed", "duplicate", "identifier"])
def test_probe_attributes_real_auditor_refusals_without_changing_verdict_or_source(
        tmp_path, monkeypatch, diagnostic, case):
    auditor_path = ROOT / "tools/verify_graph_report.py"
    auditor = diagnostic.load_auditor(auditor_path)
    raw = {"values": b'[0,0,0,0,0,0,0,0]', "depth": b'[[[[0]]]]',
           "malformed": b'{"CANARY_NEVER_EXPOSED":}',
           "duplicate": b'{"CANARY_NEVER_EXPOSED":0,"CANARY_NEVER_EXPOSED":1}',
           "identifier": b'{"directed":false,"multigraph":false,"nodes":[{"id":""}],"links":[]}'}[case]
    if case == "values":
        monkeypatch.setattr(auditor, "MAX_JSON_VALUES", 4)
    if case == "depth":
        monkeypatch.setattr(auditor, "MAX_JSON_DEPTH", 2)
    graph_path, report = audit_inputs(tmp_path, raw)
    before = auditor.audit_graph_report(graph_path, report).as_dict()
    bounds = {key: getattr(auditor, key) for key in diagnostic.BOUND_NAMES}
    previous = sys.gettrace()
    result = diagnostic.observe(auditor, graph_path, report)
    assert sys.gettrace() is previous
    assert auditor.audit_graph_report(graph_path, report).as_dict() == before
    assert {key: getattr(auditor, key) for key in bounds} == bounds
    assert before["status"] == "block" and before["error_codes"] == ["graph_report_graph_invalid"]
    assert result["status"] == "observed_block" and result["promotes_export"] is False
    assert result["probe_audited_graph"] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert "CANARY_NEVER_EXPOSED" not in json.dumps(result)
    assert set(result["first_refusal"]) == {"function", "line", "code", "counters"}
    if case == "values":
        assert result["first_refusal"]["counters"]["values"] == 5
        assert result["first_refusal"]["counters"]["container_depth"] <= auditor.MAX_JSON_DEPTH
    if case == "depth":
        assert result["first_refusal"]["counters"]["container_depth"] == 3
        assert result["first_refusal"]["counters"]["values"] <= auditor.MAX_JSON_VALUES
    if case == "duplicate":
        assert result["first_refusal"]["function"] == "_object_no_duplicates"
    if case == "identifier":
        assert result["first_refusal"]["function"] == "_identifier"
    assert hashlib.sha256(auditor_path.read_bytes()).hexdigest() == diagnostic.AUDITOR_SHA256


def test_probe_refuses_unknown_auditor_before_executing_it(tmp_path, diagnostic):
    source = tmp_path / "unreviewed.py"
    source.write_text("raise AssertionError('must not execute')\n", encoding="utf-8")
    with pytest.raises(diagnostic.ProbeUnavailable, match="auditor_revision_mismatch"):
        diagnostic.load_auditor(source)


def test_probe_does_not_promote_a_later_passing_read(tmp_path, diagnostic):
    auditor = diagnostic.load_auditor(ROOT / "tools/verify_graph_report.py")
    auditor.audit_graph_report = lambda *args: auditor.AuditResult("pass", (), {})
    result = diagnostic.observe(auditor, tmp_path / "graph.json", tmp_path / "report.md")
    assert result["status"] == "not_reproduced" and result["promotes_export"] is False


def test_probe_transport_never_echoes_unexpected_exception(tmp_path, monkeypatch, capsys, diagnostic):
    monkeypatch.setattr(diagnostic, "load_auditor", lambda *args: (_ for _ in ()).throw(
        ValueError("CANARY_NEVER_EXPOSED")))
    assert diagnostic.main(["--auditor", str(tmp_path / "auditor.py"),
                            str(tmp_path / "graph.json"), str(tmp_path / "report.md")]) == 0
    output = capsys.readouterr().out
    assert "CANARY_NEVER_EXPOSED" not in output
    assert json.loads(output)["reason"] == "probe_failed"


def test_probe_restores_trace_after_unexpected_failure(tmp_path, diagnostic):
    auditor = diagnostic.load_auditor(ROOT / "tools/verify_graph_report.py")
    auditor.audit_graph_report = lambda *args: (_ for _ in ()).throw(RuntimeError("private detail"))
    previous = sys.gettrace()
    with pytest.raises(RuntimeError):
        diagnostic.observe(auditor, tmp_path / "graph.json", tmp_path / "report.md")
    assert sys.gettrace() is previous


@pytest.mark.parametrize("status", ["observed_block", "not_reproduced", "unavailable"])
def test_diagnostic_never_promotes_original_refusal(tmp_path, monkeypatch, status):
    for key, value in environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(subject, "git", lambda root, *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(subject, "generate", lambda *args: (_ for _ in ()).throw(
        subject.Refusal("report_audit_refused")))
    probe = {"schema": "atlas-knowledge-report-diagnostic/1", "status": status, "promotes_export": False}
    monkeypatch.setattr(subject, "report_diagnostic", lambda root: probe)
    output, diagnostics = tmp_path / "output", tmp_path / "diagnostics"
    assert subject.main(["--source-root", str(tmp_path / "source"),
                         "--expected-source-commit", subject.SOURCE_COMMIT,
                         "--output", str(output), "--diagnostics", str(diagnostics)]) == 1
    assert json.loads((diagnostics / "failure.json").read_bytes())["importable_vault"] is False
    assert json.loads((diagnostics / "report-diagnostic.json").read_bytes()) == probe
    assert not output.exists()


@pytest.mark.parametrize("failure", ["timeout", "large", "malformed", "extra_fields"])
def test_probe_transport_is_bounded_and_credential_free(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(subject, "source_identity", lambda root: {})
    monkeypatch.setenv("GITHUB_TOKEN", "CANARY_NEVER_EXPOSED")

    def fake_run(command, **kwargs):
        assert command[1:3] == ["-I", "-B"] and kwargs["timeout"] == 60
        assert "CANARY_NEVER_EXPOSED" not in kwargs["env"].values()
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        raw = {"large": b" " * 8193, "malformed": b"{",
               "extra_fields": b'{"schema":"atlas-knowledge-report-diagnostic/1",'
               b'"status":"unavailable","promotes_export":false,"payload":"CANARY_NEVER_EXPOSED"}'}[failure]
        return SimpleNamespace(returncode=0, stdout=raw)

    monkeypatch.setattr(subject.subprocess, "run", fake_run)
    result = subject.report_diagnostic(tmp_path)
    assert result["status"] == "unavailable" and result["promotes_export"] is False
    assert "CANARY_NEVER_EXPOSED" not in json.dumps(result)
