from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MASTER_REFERENCE))

import continuity.__main__ as continuity_main  # noqa: E402
import continuity.enhance as enhance_module  # noqa: E402
import continuity.git_state as git_state  # noqa: E402
from continuity.enhance import build_enhancement_package  # noqa: E402
from continuity.corpus import load_enhancement_corpus  # noqa: E402
from continuity.model import (  # noqa: E402
    ContinuityInputError,
    canonical_json,
    digest_object,
    sha256_bytes,
)


@dataclass
class FakeBundle:
    source_commit: str
    source_tree_digest: str
    manifest: dict[str, Any]
    completeness: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]


def _git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Enhancement Test",
            "GIT_AUTHOR_EMAIL": "enhancement@example.invalid",
            "GIT_COMMITTER_NAME": "Enhancement Test",
            "GIT_COMMITTER_EMAIL": "enhancement@example.invalid",
            "GIT_AUTHOR_DATE": "2026-08-07T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-08-07T00:00:00Z",
        }
    )
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    return process.stdout


def _write(root: Path, relative: str, value: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _architecture() -> dict[str, Any]:
    return {
        "components": [
            {
                "id": "engine",
                "layer": 1,
                "trust_zone": "derived_truth",
                "paths": ["src/"],
            },
            {
                "id": "master_reference",
                "layer": 2,
                "trust_zone": "private_read_only",
                "paths": ["master-reference/"],
            },
            {
                "id": "release_distribution",
                "layer": 3,
                "trust_zone": "release",
                "paths": [".github/"],
            },
        ],
        "exclusions": [
            {
                "id": "verification_source",
                "paths": ["tests/"],
            }
        ],
        "allowed_edges": [],
        "forbidden_edges": [],
        "runtime_phases": [{"id": "read", "order": 1, "required": True}],
    }


def _governance() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "governance-fixture",
        "gaps": [
            {
                "id": "gap.fixture",
                "title": "Fixture gap",
                "disposition": "evidence-first",
                "problem": "No code impact is declared by this gap record.",
                "next_actions": ["Collect owned evidence."],
                "acceptance_evidence": ["Owner-reviewed evidence receipt."],
                "owner_role": "fixture owner",
            }
        ],
    }


def _source_record(file_record: dict[str, Any], raw: bytes, index: int) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="strict")
    lines: list[dict[str, Any]] = []
    for number, material in enumerate(text.splitlines(keepends=True), start=1):
        if material.endswith("\r\n"):
            line, terminator = material[:-2], "\r\n"
        elif material.endswith("\n"):
            line, terminator = material[:-1], "\n"
        elif material.endswith("\r"):
            line, terminator = material[:-1], "\r"
        else:
            line, terminator = material, ""
        lines.append({"number": number, "text": line, "terminator": terminator})
    assert "".join(str(item["text"]) + str(item["terminator"]) for item in lines) == text
    return {
        "id": f"urn:atlas:source-text:{index}",
        "file_id": file_record["id"],
        "path": file_record["path"],
        "source_basis": "selected_commit_git_blob",
        "git_blob_oid": file_record["git_blob_oid"],
        "byte_count": len(raw),
        "content_digest": sha256_bytes(raw),
        "lines": lines,
    }


def _fixture(tmp_path: Path, *, metadata_terminator: str = "\n") -> tuple[Path, FakeBundle]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    architecture_raw = json.dumps(_architecture(), ensure_ascii=False, sort_keys=True) + metadata_terminator
    governance_raw = json.dumps(_governance(), ensure_ascii=False, sort_keys=True) + metadata_terminator
    values = {
        "master-reference/governance/architecture.json": architecture_raw,
        "master-reference/content/delivery-governance.json": governance_raw,
        "src/app.py": "from src.dep import dep\n\ndef app():\n    return dep()\n",
        "src/dep.py": "def dep():\n    return 1\n",
        "tests/test_app.py": "def test_app():\n    assert True\n",
        ".github/workflows/ci.yml": "name: CI\non: [push]\n",
    }
    for relative, value in values.items():
        _write(repo, relative, value)
    _git(repo, "add", "--all")
    _git(repo, "commit", "-qm", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")

    files: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    for index, relative in enumerate(sorted(values)):
        blob_oid = _git(repo, "rev-parse", f"HEAD:{relative}")
        raw = _git_bytes(repo, "cat-file", "blob", blob_oid)
        record = {
            "id": f"urn:atlas:file:{index}",
            "path": relative,
            "git_mode": "100644",
            "git_blob_oid": blob_oid,
            "git_stage": 0,
            "content_source": "selected_commit_git_blob",
            "privacy_exposure": "full",
            "classification_errors": [],
            "size_bytes": len(raw),
            "content_digest": sha256_bytes(raw),
        }
        files.append(record)
        by_path[relative] = record

    app_file = by_path["src/app.py"]["id"]
    dep_file = by_path["src/dep.py"]["id"]
    test_file = by_path["tests/test_app.py"]["id"]
    workflow_file = by_path[".github/workflows/ci.yml"]["id"]
    symbol_app = "urn:atlas:symbol:app"
    symbol_dep = "urn:atlas:symbol:dep"
    call_dep = "urn:atlas:call:dep"
    test_app = "urn:atlas:test:app"
    route_app = "urn:atlas:route:app"
    component_app = "urn:atlas:component:app"
    workflow_ci = "urn:atlas:workflow:ci"
    graph_app = "urn:atlas:graph-node:app"
    graph_dep = "urn:atlas:graph-node:dep"
    records = {
        "files": files,
        "lines": [
            {
                "id": "urn:atlas:line:app",
                "file_id": app_file,
                "path": "src/app.py",
                "line_number": 3,
                "syntax_kind": "FunctionDef",
                "structural_mapping_basis": "symbol_range",
                "semantic_entity": symbol_app,
                "tests_covering_it": [test_app],
                "unresolved_reasons": [],
            }
        ],
        "source_text": [
            _source_record(
                by_path["master-reference/governance/architecture.json"],
                architecture_raw.encode("utf-8"),
                1,
            ),
            _source_record(
                by_path["master-reference/content/delivery-governance.json"],
                governance_raw.encode("utf-8"),
                2,
            ),
        ],
        "symbols": [
            {
                "id": symbol_app,
                "file_id": app_file,
                "path": "src/app.py",
                "name": "app",
                "qualified_name": "app",
                "purpose": "Return the dependency result.",
                "callees": [call_dep],
                "tests": [test_app],
                "downstream_surfaces": [route_app, component_app],
                "known_impact_if_changed": [workflow_ci],
                "explanation_depth": 1,
                "unresolved_reasons": ["runtime_trace_not_collected"],
            },
            {
                "id": symbol_dep,
                "file_id": dep_file,
                "path": "src/dep.py",
                "name": "dep",
                "qualified_name": "dep",
                "explanation_depth": 1,
                "unresolved_reasons": [],
            },
        ],
        "structural_entities": [
            {
                "id": "urn:atlas:structural-entity:app",
                "file_id": app_file,
                "path": "src/app.py",
                "root_scope": "parsed_source",
                "range": {"start_line": 1, "end_line": 5},
                "line_count": 5,
                "parser_owned": True,
            }
        ],
        "imports": [
            {
                "id": "urn:atlas:import:dep",
                "file_id": app_file,
                "path": "src/app.py",
                "module": "src.dep",
                "names": ["dep"],
            }
        ],
        "calls": [
            {
                "id": call_dep,
                "file_id": app_file,
                "path": "src/app.py",
                "callee": "dep",
                "semantic_entity": symbol_app,
            }
        ],
        "tests": [
            {
                "id": test_app,
                "file_id": test_file,
                "path": "tests/test_app.py",
                "name": "test_app",
            }
        ],
        "routes": [
            {
                "id": route_app,
                "file_id": app_file,
                "path": "src/app.py",
                "name": "/app",
            }
        ],
        "components": [
            {
                "id": component_app,
                "file_id": app_file,
                "path": "src/app.py",
                "name": "App",
            }
        ],
        "workflows": [
            {
                "id": workflow_ci,
                "file_id": workflow_file,
                "path": ".github/workflows/ci.yml",
                "name": "CI",
            }
        ],
        "graph_nodes": [
            {
                "id": graph_app,
                "file_id": app_file,
                "source_file": "src/app.py",
                "label": "app",
            },
            {
                "id": graph_dep,
                "file_id": dep_file,
                "source_file": "src/dep.py",
                "label": "dep",
            },
        ],
        "graph_edges": [
            {
                "id": "urn:atlas:graph-edge:app-dep",
                "source": graph_app,
                "target": graph_dep,
                "relation": "calls",
                "extraction_mode": "extracted",
            }
        ],
        "claims": [
            {
                "id": "urn:atlas:claim:app",
                "predicate": "fixture.app.exists",
                "evidence_ids": [symbol_app],
            }
        ],
        "datasets": [],
        "binaries": [],
        "dependencies": [],
    }
    completeness = {
        "schema_version": "1.1.0",
        "id": "urn:atlas:completeness:fixture",
        "hard_failure": False,
        "fatal_errors": [],
        "invariants": [
            {
                "name": "every_safe_line_structurally_mapped",
                "passed": True,
                "expected": 1,
                "actual": 1,
            },
            {
                "name": "every_gui_surface_has_standardized_evidence_honest_dossier",
                "passed": True,
                "expected": 2,
                "actual": 2,
            },
            {
                "name": "every_safe_parsed_source_has_one_structural_root",
                "passed": True,
                "expected": 1,
                "actual": 1,
            },
        ],
        "acceptance_gates": [
            {
                "name": "runtime_trace_evidence_joined_to_source_records",
                "passed": False,
                "expected": 1,
                "actual": 0,
            }
        ],
        "semantic_accounting": {
            "runtime_trace_state": "not_collected",
            "coverage_evidence_state": "structural_links_only",
        },
        "graphify": {"available": True, "status": "current", "stale": False},
    }
    bundle = FakeBundle(
        source_commit=commit,
        source_tree_digest="c" * 64,
        manifest={
            "schema_version": "1.1.0",
            "source_commit": commit,
            "source_tree_digest": "c" * 64,
            "release_class": "exact_commit",
            "tracked_worktree_dirty": False,
            "head_tree_oid": tree,
            "index_digest": digest_object(
                [
                    {
                        "mode": item["git_mode"],
                        "blob_oid": item["git_blob_oid"],
                        "stage": item["git_stage"],
                        "path": item["path"],
                    }
                    for item in files
                ]
            ),
            "groups": {
                group: {"record_count": len(group_records)}
                for group, group_records in records.items()
            },
        },
        completeness=completeness,
        records=records,
    )
    return repo, bundle


def _compiler_output(root: Path, bundle: FakeBundle) -> Path:
    root.mkdir(parents=True)

    def emit(relative: str, value: dict[str, Any]) -> dict[str, Any]:
        raw = canonical_json(value)
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": relative, "bytes": len(raw), "sha256": sha256_bytes(raw)}

    groups: dict[str, Any] = {}
    for group, records in sorted(bundle.records.items()):
        chunks: list[dict[str, Any]] = []
        if records:
            envelope = {
                "schema_version": "1.1.0",
                "record_type": group,
                "source_commit": bundle.source_commit,
                "source_tree_digest": bundle.source_tree_digest,
                "chunk_index": 0,
                "chunk_count": 1,
                "record_count": len(records),
                "records_digest": digest_object([record["id"] for record in records]),
                "records": records,
            }
            chunks.append(emit(f"records/{group}/00000.json", envelope))
            chunks[0]["record_count"] = len(records)
        groups[group] = {
            "record_count": len(records),
            "records_digest": digest_object([record["id"] for record in records]),
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

    graphify = {"schema_version": "1.1.0", **bundle.completeness["graphify"]}
    architecture = {
        "schema_version": "1.1.0",
        "source_commit": bundle.source_commit,
        "source_tree_digest": bundle.source_tree_digest,
        "status": "passed",
        "errors": [],
        "runtime_observed": False,
    }
    completeness = copy.deepcopy(bundle.completeness)
    completeness.update(
        {
            "source_commit": bundle.source_commit,
            "source_tree_digest": bundle.source_tree_digest,
            "graphify": graphify,
            "architecture_conformance": architecture,
        }
    )
    manifest = {
        **bundle.manifest,
        "status": "complete",
        "groups": groups,
        "completeness": emit("completeness.json", completeness),
        "graphify_metadata": emit("graphify.json", graphify),
        "architecture_conformance": emit("architecture.json", architecture),
    }
    root.joinpath("manifest.json").write_bytes(canonical_json(manifest))
    return root


def _workspace_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_exact_closure_is_deterministic_cited_and_read_only(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    before = _workspace_snapshot(repo)
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    code, first = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:symbol:app",
        max_depth=4,
        max_records=100,
        max_edges=200,
    )
    second_code, second = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:symbol:app",
        max_depth=4,
        max_records=100,
        max_edges=200,
    )

    assert code == second_code == 0
    assert canonical_json(first) == canonical_json(second)
    assert first["status"] == "answered"
    assert first["source_binding"]["observed_changed_paths"] == []
    assert first["dependency_and_impact_closure"]["traversal"]["truncated"] is False
    record_types = set(first["dependency_and_impact_closure"]["record_type_counts"])
    assert {
        "calls",
        "claims",
        "components",
        "files",
        "graph_edges",
        "graph_nodes",
        "imports",
        "routes",
        "symbols",
        "tests",
        "workflows",
    }.issubset(record_types)
    relations = {
        item["relation"] for item in first["dependency_and_impact_closure"]["edges"]
    }
    assert "statically_resolved_import_path" in relations
    assert "static_callee_name_candidate" in relations
    assert all(item["citation"]["source_commit"] == bundle.source_commit for item in first["dependency_and_impact_closure"]["records"])
    assert {item["id"] for item in first["affected_architecture_owners"]} == {
        "engine",
        "release_distribution",
        "verification_source",
    }
    assert {item["kind"] for item in first["known_gui_or_artifact_surfaces"]} >= {
        "components",
        "routes",
        "workflows",
    }
    assert first["required_tests_and_gates"]["existing_test_records"]
    assert first["rollback_and_kill_conditions"]["rollback_mechanism"] is None
    assert first["side_effects"] == "none"
    assert _workspace_snapshot(repo) == before
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_gap_seed_uses_exact_governance_and_does_not_invent_code_impact(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="gap",
        seed_value="gap.fixture",
    )

    assert code == 0
    assert result["current_record"]["record"]["title"] == "Fixture gap"
    assert result["current_record"]["citation"]["sha256"] == next(
        item["content_digest"]
        for item in bundle.records["files"]
        if item["path"] == "master-reference/content/delivery-governance.json"
    )
    assert result["smallest_safe_vertical_slice"]["status"] == "blocked_pending_evidence"
    assert "no_gui_or_artifact_surface_linked" in {
        item["category"] for item in result["unresolved_impact_categories"]
    }
    closure_ids = {
        item["id"] for item in result["dependency_and_impact_closure"]["records"]
    }
    assert "urn:atlas:symbol:app" not in closure_ids


def test_line_seed_reaches_declared_test_and_same_file_surfaces(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)

    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:line:app",
    )

    assert code == 0
    closure_ids = {
        item["id"] for item in result["dependency_and_impact_closure"]["records"]
    }
    assert "urn:atlas:test:app" in closure_ids
    assert "urn:atlas:route:app" in closure_ids
    assert "urn:atlas:component:app" in closure_ids
    assert any(
        edge["relation"] == "tests_covering_it"
        and edge["source"] == "urn:atlas:line:app"
        and edge["target"] == "urn:atlas:test:app"
        for edge in result["dependency_and_impact_closure"]["edges"]
    )


def test_missing_seed_or_gap_evidence_abstains(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    code, missing = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:symbol:missing",
    )
    assert code == 3
    assert missing["reason"] == "stable_seed_not_found_in_exact_bundle"

    without_governance = copy.deepcopy(bundle)
    governance_path = "master-reference/content/delivery-governance.json"
    governance_file_ids = {
        item["id"]
        for item in without_governance.records["files"]
        if item["path"] == governance_path
    }
    without_governance.records["source_text"] = [
        item
        for item in without_governance.records["source_text"]
        if item["file_id"] not in governance_file_ids
    ]
    governance_file = next(
        item
        for item in without_governance.records["files"]
        if item["path"] == governance_path
    )
    governance_file["privacy_exposure"] = "metadata_only"
    governance_file["content_source"] = "metadata_only_git_object"
    governance_file["content_digest"] = None
    code, missing_gap = build_enhancement_package(
        without_governance,
        repo,
        seed_kind="gap",
        seed_value="gap.fixture",
    )
    assert code == 3
    assert missing_gap["reason"] == "gap_governance_evidence_unavailable"


def test_stale_dirty_or_preview_source_is_rejected(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    _write(repo, "src/app.py", "def changed():\n    return 2\n")
    with pytest.raises(ContinuityInputError, match="dirty"):
        build_enhancement_package(
            bundle,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:symbol:app",
        )

    _git(repo, "add", "src/app.py")
    _git(repo, "commit", "-qm", "new head")
    with pytest.raises(ContinuityInputError, match="stale"):
        build_enhancement_package(
            bundle,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:symbol:app",
        )

    preview = copy.deepcopy(bundle)
    preview.manifest["release_class"] = "dirty_preview"
    preview.manifest["tracked_worktree_dirty"] = True
    with pytest.raises(ContinuityInputError, match="exact_commit"):
        build_enhancement_package(
            preview,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:symbol:app",
        )


def test_hidden_worktree_state_is_rejected_by_index_flag(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    _git(repo, "update-index", "--assume-unchanged", "src/app.py")
    _write(repo, "src/app.py", "def hidden():\n    return 9\n")
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""

    with pytest.raises(ContinuityInputError, match="nonstandard_index_flag"):
        build_enhancement_package(
            bundle,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:symbol:app",
        )


def test_traversal_limits_are_enforced_and_disclosed(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:symbol:app",
        max_depth=0,
        max_records=1,
        max_edges=1,
    )
    assert code == 0
    traversal = result["dependency_and_impact_closure"]["traversal"]
    assert traversal["truncated"] is True
    assert "max_depth_reached" in traversal["truncation_reasons"]
    assert result["smallest_safe_vertical_slice"]["status"] == "blocked_pending_evidence"
    assert "bounded_closure_truncated" in {
        item["category"] for item in result["unresolved_impact_categories"]
    }


def test_cli_enhance_dispatches_exact_seed_and_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, bundle = _fixture(tmp_path)
    compiler_output = _compiler_output(tmp_path / "compiler", bundle)
    monkeypatch.setattr(
        continuity_main,
        "load_compiler_bundle",
        lambda _path: (_ for _ in ()).throw(AssertionError("enhance called the all-groups release loader")),
    )
    arguments = continuity_main._parser().parse_args(
        [
            "enhance",
            "--repo-root",
            str(repo),
            "--compiler-output",
            str(compiler_output),
            "--file",
            "src/app.py",
            "--max-depth",
            "2",
            "--max-records",
            "20",
            "--max-edges",
            "40",
        ]
    )
    code, result = continuity_main._run(arguments)
    assert code == 0
    assert result["seed"]["kind"] == "file"
    assert result["seed"]["resolved_id"].startswith("urn:atlas:file:")
    assert result["dependency_and_impact_closure"]["traversal"]["max_depth"] == 2


def test_lazy_corpus_validates_only_scanned_group_chunks(tmp_path: Path) -> None:
    _repo, bundle = _fixture(tmp_path)
    compiler_output = _compiler_output(tmp_path / "compiler", bundle)

    corpus = load_enhancement_corpus(compiler_output)
    initial = corpus.io_scan_counts()
    assert initial["validated_chunk_reads"] == 3
    assert initial["validated_group_passes"] == {}

    symbols = list(corpus.iter_group("symbols"))
    assert {record["id"] for record in symbols} == {
        "urn:atlas:symbol:app",
        "urn:atlas:symbol:dep",
    }
    after = corpus.io_scan_counts()
    assert after["validated_group_passes"] == {"symbols": 1}
    assert after["validated_chunk_reads"] == initial["validated_chunk_reads"] + 1
    assert "source_text" not in after["validated_group_passes"]


def test_cr_only_compiler_source_terminators_are_accepted(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path, metadata_terminator="\r")
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="gap",
        seed_value="gap.fixture",
    )
    assert code == 0
    assert result["current_record"]["record"]["id"] == "gap.fixture"
    assert result["current_record"]["citation"]["source_basis"] == "compiler_source_text"


def test_untracked_private_bytes_are_never_enumerated_or_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, bundle = _fixture(tmp_path)
    sentinel = repo / "innocent-cache.bin"
    private_bytes = b"client-private-byte-sentinel\x00\xff"
    sentinel.write_bytes(private_bytes)
    sentinel_resolved = sentinel.resolve()
    original_read_bytes = Path.read_bytes
    original_git = git_state._git

    def guarded_read_bytes(path: Path) -> bytes:
        if path.resolve() == sentinel_resolved:
            raise AssertionError("continuity read an untracked private sentinel")
        return original_read_bytes(path)

    def guarded_git(root: Path, *arguments: str) -> bytes:
        if arguments[:2] == ("ls-files", "--others"):
            raise AssertionError("continuity enumerated untracked paths")
        return original_git(root, *arguments)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(git_state, "_git", guarded_git)
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:symbol:app",
        max_depth=1,
        max_records=10,
        max_edges=20,
    )
    assert code == 0
    assert result["source_binding"]["observed_changed_paths"] == []
    with sentinel.open("rb") as handle:
        assert handle.read() == private_bytes


def test_tracked_git_state_is_revalidated_after_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, bundle = _fixture(tmp_path)
    original = enhance_module._bounded_impact_closure

    def mutate_after_traversal(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        _write(repo, "src/dep.py", "def changed_during_traversal():\n    return 99\n")
        return result

    monkeypatch.setattr(enhance_module, "_bounded_impact_closure", mutate_after_traversal)
    with pytest.raises(ContinuityInputError, match="tracked_status_not_clean|dirty"):
        build_enhancement_package(
            bundle,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:symbol:app",
            max_depth=1,
            max_records=10,
            max_edges=20,
        )


def test_stale_missing_and_duplicate_compiler_gates_fail_closed(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    cases: list[tuple[FakeBundle, str]] = []

    stale = copy.deepcopy(bundle)
    stale.manifest["schema_version"] = "1.0.0"
    cases.append((stale, "unsupported compiler schema"))

    missing = copy.deepcopy(bundle)
    missing.completeness["invariants"] = [
        item
        for item in missing.completeness["invariants"]
        if item["name"] != "every_gui_surface_has_standardized_evidence_honest_dossier"
    ]
    cases.append((missing, "required exact-denominator invariants are absent"))

    duplicated = copy.deepcopy(bundle)
    duplicated.completeness["invariants"].append(
        copy.deepcopy(duplicated.completeness["invariants"][0])
    )
    cases.append((duplicated, "invalid or duplicate name"))

    no_acceptance = copy.deepcopy(bundle)
    no_acceptance.completeness["acceptance_gates"] = []
    cases.append((no_acceptance, "semantic acceptance gates are absent"))

    for candidate, message in cases:
        with pytest.raises(ContinuityInputError, match=message):
            build_enhancement_package(
                candidate,
                repo,
                seed_kind="id",
                seed_value="urn:atlas:symbol:app",
            )


def test_non_symbol_line_requires_same_file_parser_owned_structural_root(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    line = bundle.records["lines"][0]
    line["structural_mapping_basis"] = "parser_structural_root"
    line["semantic_entity"] = "urn:atlas:structural-entity:app"
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value="urn:atlas:line:app",
        max_depth=1,
    )
    assert code == 0
    assert result["seed"]["resolved_id"] == "urn:atlas:line:app"

    invalid = copy.deepcopy(bundle)
    invalid.records["lines"][0]["semantic_entity"] = invalid.records["lines"][0]["file_id"]
    with pytest.raises(ContinuityInputError, match="file ownership may not qualify"):
        build_enhancement_package(
            invalid,
            repo,
            seed_kind="id",
            seed_value="urn:atlas:line:app",
        )


def test_large_corpus_retention_and_output_remain_bounded(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    seed_id = "urn:atlas:symbol:app"
    bundle.records["claims"].extend(
        {
            "id": f"urn:atlas:claim:bulk-{index:05d}",
            "predicate": f"fixture.bulk.{index}",
            "evidence_ids": [seed_id],
        }
        for index in range(12_000)
    )
    bundle.manifest["groups"]["claims"]["record_count"] = len(bundle.records["claims"])

    tracemalloc.start()
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value=seed_id,
        max_depth=1,
        max_records=5,
        max_edges=4,
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert code == 0
    traversal = result["dependency_and_impact_closure"]["traversal"]
    assert traversal["included_records"] <= 5
    assert traversal["included_edges"] <= 4
    assert len(result["dependency_and_impact_closure"]["records"]) <= 5
    assert len(result["dependency_and_impact_closure"]["edges"]) <= 4
    assert traversal["construction_model"] == "seed_directed_streaming_no_global_record_graph"
    assert result["corpus_scan"]["record_scans_by_group"]["claims"] >= 12_000
    assert len(canonical_json(result)) <= enhance_module.MAX_SERIALIZED_OUTPUT_BYTES
    assert peak < 12 * 1024 * 1024


def test_source_text_stable_id_seed_abstains_without_scanning_source_text(tmp_path: Path) -> None:
    repo, bundle = _fixture(tmp_path)
    source_id = bundle.records["source_text"][0]["id"]
    code, result = build_enhancement_package(
        bundle,
        repo,
        seed_kind="id",
        seed_value=source_id,
    )
    assert code == 3
    assert result["reason"] == "source_text_seed_is_unbounded_use_file_or_line_query"
    assert "source_text" not in result["corpus_scan"]["record_scans_by_group"]
