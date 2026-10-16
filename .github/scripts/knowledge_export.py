"""Hosted-only, nonpromoting Graphify/Obsidian handoff for one reviewed RC7 tree.

No local graph, owner memory, linked worktree or personal vault is an input. The
existing report verifier and producer/exporter guards retain their exact bounds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

SOURCE_COMMIT = "3401627f6fd69bb838a2c921d7f95c77b2373623"
SOURCE_TREE = "1aaa1cb7d87712d8cfcbb19a42e0c4a7ec68d5a8"
REPOSITORY = "Tanveerahamed-Dev/cisco-migration-assessment-toolkit"
SCHEMA = "atlas-knowledge-export/1"
GRAPH_MEMBERS = ("graph.json", "GRAPH_REPORT.md", ".graphify_labels.json",
                 ".graphify_labels.json.sig", ".guarded_refresh.json")
CORPUS_LIMITS = ["graph_corpus_memory_ignore_override", "graph_corpus_authored_build_dir_pruned",
                 "structural_markdown_only", "no_local_untracked_or_owner_memory"]


class Refusal(RuntimeError):
    """Fixed, non-echoing refusal code; never approval or a verifier override."""


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_bytes(canonical(value))


def admit(environment, requested):
    if (environment.get("GITHUB_ACTIONS") != "true"
            or environment.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or environment.get("GITHUB_REPOSITORY") != REPOSITORY):
        raise Refusal("hosted_manual_execution_required")
    if requested != SOURCE_COMMIT:
        raise Refusal("unreviewed_source_revision")
    if not re.fullmatch(r"[0-9a-f]{40}", environment.get("GITHUB_SHA", "")):
        raise Refusal("controller_revision_invalid")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not re.fullmatch(r"[1-9][0-9]*", environment.get(key, "")):
            raise Refusal("run_identity_invalid")


def child_environment():
    # A producer gets OS/interpreter lookup only, never provider keys, GitHub
    # tokens, inherited graph/Git switches or model/URL source configuration.
    allowed = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TZ="UTC",
               GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
    return env


def git(root, *arguments):
    executable = shutil.which("git")
    if not executable:
        raise Refusal("git_unavailable")
    completed = subprocess.run(
        [executable, "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
         f"--git-dir={root / '.git'}", f"--work-tree={root}", *arguments],
        cwd=root, env=child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    if completed.returncode:
        raise Refusal("source_git_unreadable")
    return completed.stdout.decode("utf-8", "strict").strip()


def source_identity(root):
    marker = root / ".git"
    if not marker.is_dir() or marker.is_symlink() or (marker / "commondir").exists():
        raise Refusal("standalone_source_checkout_required")
    head, tree = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")
    if (head, tree) != (SOURCE_COMMIT, SOURCE_TREE):
        raise Refusal("source_revision_mismatch")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise Refusal("source_checkout_not_clean")
    return {"commit": head, "tree": tree, "tracked_status": "clean"}


def run(source, output, phase, tool, *arguments):
    command = [sys.executable, "-I", "-B", str(source / tool), *map(str, arguments)]
    try:
        result = subprocess.run(command, cwd=source, env=child_environment(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
    except subprocess.TimeoutExpired as exc:
        raise Refusal(f"{phase}_timeout") from exc
    (output / "logs" / f"{phase}.txt").write_bytes(result.stdout)
    if result.returncode:
        raise Refusal(f"{phase}_refused")
    return result.stdout.decode("utf-8", "strict").strip()


def report_diagnostic(source):
    unavailable = {"schema": "atlas-knowledge-report-diagnostic/1", "status": "unavailable",
                   "reason": "probe_unavailable", "promotes_export": False}
    try:
        source_identity(source)
        helper = Path(__file__).with_name("knowledge_report_diagnostics.py")
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(helper), "--auditor", str(source / "tools/verify_graph_report.py"),
             str(source / "graphify-out/graph.json"), str(source / "graphify-out/GRAPH_REPORT.md")],
            cwd=source, env=child_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
        )
        source_identity(source)
        if result.returncode or len(result.stdout) > 8192:
            return unavailable
        payload = json.loads(result.stdout)
        allowed = {"schema", "status", "reason", "promotes_export", "auditor_sha256", "audit_status",
                   "audit_error_codes", "first_refusal", "probe_audited_graph", "bounds"}
        if (not isinstance(payload, dict) or payload.get("schema") != unavailable["schema"]
                or payload.get("status") not in {"observed_block", "not_reproduced", "unavailable"}
                or set(payload) - allowed
                or payload.get("promotes_export") is not False):
            return unavailable
        return payload
    except (Refusal, OSError, ValueError, subprocess.SubprocessError):
        return unavailable


def regular_bytes(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or path.is_symlink():
        raise Refusal("nonregular_output_member")
    raw = path.read_bytes()
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != after.st_size):
        raise Refusal("output_member_changed")
    return raw


def rows(root):
    result = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink():
            raise Refusal("linked_output_member")
        if path.is_dir():
            continue
        raw = regular_bytes(path)
        result.append({"path": path.relative_to(root).as_posix(), "bytes": len(raw), "sha256": digest(raw)})
    if len({row["path"].casefold() for row in result}) != len(result):
        raise Refusal("casefold_member_collision")
    return result


def validate_graph(graph):
    if graph.get("built_at_commit") != SOURCE_COMMIT:
        raise Refusal("graph_source_stamp_mismatch")
    nodes, edges = graph["nodes"], graph["links"]
    ids = {node["id"] for node in nodes}
    if not ids or len(ids) != len(nodes):
        raise Refusal("graph_identity_invalid")
    if any(node.get("_origin") not in (None, "ast") for node in nodes):
        raise Refusal("non_ast_graph_origin")
    if any(edge["source"] not in ids or edge["target"] not in ids for edge in edges):
        raise Refusal("dangling_graph_edge")
    return {"nodes": len(nodes), "edges": len(edges), "global_corpus_complete": False,
            "coverage_limits": list(CORPUS_LIMITS)}


def wiki_targets(text):
    # Consume a wikilink as one token before interpreting code delimiters:
    # reviewed exporter filenames can themselves contain literal backticks.
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        index = 0
        while index < len(line):
            if line.startswith("[[", index):
                end = line.find("]]", index + 2)
                if end != -1:
                    target = line[index + 2:end].split("|", 1)[0].split("#", 1)[0]
                    if target:
                        yield target.removesuffix(".md").casefold()
                    index = end + 2
                    continue
            if line[index] == "`":
                run_end = index
                while run_end < len(line) and line[run_end] == "`":
                    run_end += 1
                delimiter = line[index:run_end]
                close = re.search(r"(?<!`)" + re.escape(delimiter) + r"(?!`)", line[run_end:])
                index = run_end + close.end() if close else run_end
            else:
                index += 1


def validate_vault(vault, graph, graph_raw, labels_raw):
    receipt_name = "atlas-obsidian-receipt.json"
    ledger = rows(vault)
    receipt = json.loads(regular_bytes(vault / receipt_name))
    members = [row for row in ledger if row["path"] != receipt_name]
    if (receipt.get("graph_sha256") != digest(graph_raw)
            or receipt.get("labels_sha256") != digest(labels_raw)
            or receipt.get("member_count_excluding_receipt") != len(members)
            or receipt.get("member_digest_excluding_receipt") != digest(canonical(members))
            or receipt.get("node_count") != len(graph["nodes"])
            or receipt.get("absolute_root_embedded") is not False):
        raise Refusal("vault_receipt_mismatch")
    markdown = {row["path"][:-3].casefold() for row in members if row["path"].endswith(".md")}
    actual_ids = []
    links = 0
    for member in members:
        relative = member["path"]
        # Leaves enough room for a fresh Windows destination root of 120 UTF-16 units.
        if len(relative.encode("utf-16-le")) // 2 + 121 > 259:
            raise Refusal("vault_windows_path_budget")
        if relative.endswith(".md"):
            stem = relative[:-3]
            identity = re.search(r"--([0-9a-f]{16})$", stem)
            if identity:
                actual_ids.append(identity.group(1))
            for target in wiki_targets((vault / relative).read_text(encoding="utf-8")):
                links += 1
                if target not in markdown:
                    raise Refusal("vault_dangling_wikilink")
    expected_ids = {digest(node["id"].encode("utf-8"))[:16] for node in graph["nodes"]}
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        raise Refusal("vault_node_identity_coverage")
    canvas = json.loads(regular_bytes(vault / "graph.canvas"))
    member_paths = {member["path"] for member in members}
    canvas_ids = {node["id"] for node in canvas["nodes"]}
    if len(canvas_ids) != len(canvas["nodes"]):
        raise Refusal("canvas_duplicate_identity")
    for node in canvas["nodes"]:
        if node.get("type") == "file":
            target = PurePosixPath(node["file"])
            if target.is_absolute() or ".." in target.parts or target.as_posix() not in member_paths:
                raise Refusal("canvas_file_reference_invalid")
    for edge in canvas.get("edges", []):
        if edge["fromNode"] not in canvas_ids or edge["toNode"] not in canvas_ids:
            raise Refusal("canvas_edge_reference_invalid")
    return {"members": len(ledger), "markdown_notes": len(markdown), "wikilinks_checked": links,
            "member_digest": digest(canonical(members)), "windows_destination_root_max_units": 120}


def generate(source, output, expected):
    identity = source_identity(source)
    if (source / "graphify-out").exists():
        raise Refusal("fresh_source_without_owner_graph_required")
    output.mkdir()
    (output / "logs").mkdir()
    guard = "tools/graphify_guarded.py"
    run(source, output, "producer_probe", guard, "--probe")
    run(source, output, "source_privacy", ".github/scripts/verify_repository_privacy.py", "--root", source)
    run(source, output, "bootstrap", guard, "extract", ".", "--code-only")
    before = run(source, output, "identity_before", guard, "--identity")
    if before.split("\t")[:2] != [expected, "clean"]:
        raise Refusal("guarded_source_identity_mismatch")
    receipt = source / "graphify-out/.guarded_refresh.json"
    run(source, output, "receipt_pending", guard, "--receipt-pending", receipt, expected, "clean")
    run(source, output, "full_update", guard, "update", ".")
    if run(source, output, "identity_after", guard, "--identity") != before:
        raise Refusal("source_changed_during_generation")
    run(source, output, "receipt_complete", guard, "--receipt-complete", receipt, expected, "clean")
    run(source, output, "receipt_status", guard, "--receipt-status", receipt, expected, "clean")
    graph_dir = source / "graphify-out"
    # This is deliberately the unchanged existing audit, including its 2M lexical-value cap.
    audit = json.loads(run(source, output, "report_audit", "tools/verify_graph_report.py",
                           graph_dir / "graph.json", graph_dir / "GRAPH_REPORT.md"))
    if audit.get("status") != "pass":
        raise Refusal("report_audit_not_pass")
    frozen = {member: regular_bytes(graph_dir / member) for member in GRAPH_MEMBERS}
    graph = json.loads(frozen["graph.json"])
    graph_check = validate_graph(graph)
    with tempfile.TemporaryDirectory(prefix="atlas-knowledge-", dir=output.parent) as temporary:
        vault = Path(temporary) / "obsidian"
        run(source, output, "obsidian_export", "tools/export_graphify_obsidian.py",
            "--graph", graph_dir / "graph.json", "--labels", graph_dir / ".graphify_labels.json", "--dir", vault)
        vault_check = validate_vault(vault, graph, frozen["graph.json"], frozen[".graphify_labels.json"])
        with zipfile.ZipFile(output / "obsidian.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in rows(vault):
                info = zipfile.ZipInfo(member["path"], date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                archive.writestr(info, regular_bytes(vault / member["path"]), compress_type=zipfile.ZIP_DEFLATED)
    if source_identity(source) != identity or any(regular_bytes(graph_dir / k) != v for k, v in frozen.items()):
        raise Refusal("source_or_graph_changed_before_publication")
    (output / "graph").mkdir()
    for member, raw in frozen.items():
        (output / "graph" / member).write_bytes(raw)
    proof = {"schema": SCHEMA, "status": "verified_export_for_review", "source": identity,
             "controller_commit": os.environ["GITHUB_SHA"], "repository": REPOSITORY,
             "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
             "report_audit": audit, "graph_checks": graph_check, "vault_checks": vault_check,
             "personal_vault_written": False, "local_dirty_worktree_covered": False,
             "source_to_output_authentication": "GitHub run binding; not a signed attestation"}
    write_json(output / "verification.json", proof)
    (output / "README.txt").write_text(
        f"ATLAS RC7 knowledge review artifact. Source {expected}.\n"
        "Read verification.json and knowledge-manifest.json. This does not certify global corpus completeness.\n"
        "Download to a fresh folder. Extract obsidian.zip ONLY to a new empty/nonexistent staging folder\n"
        "whose absolute path is at most 120 UTF-16 units. Never merge over existing notes or the personal vault.\n"
        "Open that folder as a separate Obsidian vault. Keep old hand-written notes unchanged.\n", encoding="utf-8")
    write_json(output / "knowledge-manifest.json", {"schema": SCHEMA, "source": identity, "members": rows(output)})
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--diagnostics", required=True, type=Path)
    args = parser.parse_args(argv)
    admitted_diagnostics = None
    try:
        admit(os.environ, args.expected_source_commit)
        source, output, diagnostics = (p.resolve() for p in (args.source_root, args.output, args.diagnostics))
        if (output.exists() or diagnostics.exists() or source in output.parents or source in diagnostics.parents
                or output == source or diagnostics == source or output == diagnostics
                or output in diagnostics.parents or diagnostics in output.parents):
            raise Refusal("fresh_external_destinations_required")
        admitted_diagnostics = diagnostics
        controller = Path(__file__).resolve().parents[2]
        if (git(controller, "rev-parse", "HEAD") != os.environ["GITHUB_SHA"]
                or git(controller, "status", "--porcelain=v1", "--untracked-files=all")):
            raise Refusal("controller_revision_mismatch")
        proof = generate(source, output, args.expected_source_commit)
        print(json.dumps({"status": proof["status"], "source": proof["source"]}, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Never upload the partially generated output on this path. Only fixed refusal
        # codes and the existing report audit result are preserved as BLOCKED diagnostics.
        code = str(exc) if isinstance(exc, Refusal) else "knowledge_export_failed"
        if admitted_diagnostics is not None and not admitted_diagnostics.exists():
            admitted_diagnostics.mkdir(parents=True)
            write_json(admitted_diagnostics / "failure.json", {"schema": SCHEMA, "status": "BLOCKED",
                       "source_commit": SOURCE_COMMIT, "reason": code, "importable_vault": False,
                       "report_verifier_bound_unchanged": True})
            audit_log = args.output / "logs/report_audit.txt"
            if audit_log.is_file() and audit_log.stat().st_size <= 32768:
                shutil.copyfile(audit_log, admitted_diagnostics / "report-audit.txt")
            if code == "report_audit_refused":
                write_json(admitted_diagnostics / "report-diagnostic.json", report_diagnostic(source))
        print(f"knowledge-export: BLOCKED: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
