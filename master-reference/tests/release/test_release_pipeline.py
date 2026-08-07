from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from release.compiler_bundle import REQUIRED_ACCEPTANCE_GATES, REQUIRED_GROUPS  # noqa: E402
from release.model import canonical_json, digest_object, sha256_bytes  # noqa: E402
import release.pipeline as release_pipeline  # noqa: E402
from release.pipeline import ReleaseError, build_release  # noqa: E402
from release.signing import sign_manifest, verify_artifact_family, verify_manifest  # noqa: E402
from release.schema_validation import validate_release_object  # noqa: E402


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _json(path: Path, value: object) -> None:
    _write(path, canonical_json(value))


def _git(repo: Path, *arguments: str, environment: dict[str, str] | None = None) -> bytes:
    process = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=repo,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    return process.stdout


def _fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    content_root = repo / "master-reference" / "content"
    core = {
        "schema_version": "1.0.0",
        "id": "core",
        "scope": "Synthetic repository-owned reference fixture.",
        "owners": [{"id": "owner.ssot", "path": "docs/ssot.md"}],
        "outcomes": [{"id": "outcome.one", "title": "Evidence", "success_signal": "Owned evidence reaches output."}],
        "non_goals": [{"id": "non-goal.write", "statement": "No device writes."}],
    }
    catalog = {
        "schema_version": "1.0.0",
        "id": "catalog",
        "domains": [
            {
                "id": "domain.one",
                "entries": [
                    {
                        "id": "cap.one",
                        "title": "One capability",
                        "state": "partial",
                        "current_scope": "Fixture scope.",
                        "owner_refs": ["owner.ssot"],
                        "gap_refs": ["gap.one"],
                    }
                ],
            }
        ],
    }
    governance = {
        "schema_version": "1.0.0",
        "id": "governance",
        "gaps": [
            {
                "id": "gap.one",
                "title": "One gap",
                "priority": "P0",
                "disposition": "build",
                "problem": "The fixture is deliberately incomplete.",
                "next_actions": ["Implement a bounded slice."],
                "acceptance_evidence": ["Executable proof."],
                "owner_role": "fixture owner",
            }
        ],
        "decision_queue": [
            {
                "id": "decision.one",
                "title": "Choose scope",
                "status": "open",
                "authority": "fixture owner",
                "options": ["Do nothing", "Build slice"],
                "current_recommendation": "Build the slice.",
                "evidence_needed": ["Test result"],
                "gap_refs": ["gap.one"],
            }
        ],
        "opportunity_portfolio": {
            "ranking_rule": "No aggregate score.",
            "items": [
                {
                    "id": "opp.one",
                    "title": "Fixture opportunity",
                    "gap_refs": ["gap.one"],
                    "horizon": "now",
                    "axes": {"user_value": 5, "implementation_effort": 1},
                    "axis_notes": "Synthetic only.",
                }
            ],
        },
        "invariants": [{"id": "invariant.no-write", "statement": "No device writes.", "owner_refs": ["owner.ssot"]}],
    }
    horizon = {
        "schema_version": "1.0.0",
        "id": "horizon",
        "watch_families": [{"id": "watch.one", "name": "Official source"}],
        "signals": [{"id": "signal.one", "title": "Candidate", "disposition": "watch"}],
    }
    output_contract = json.loads(
        (MASTER_REFERENCE / "content" / "output-contract.json").read_text(encoding="utf-8")
    )
    content_values = {
        "atlas-core.json": core,
        "capability-catalog.json": catalog,
        "delivery-governance.json": governance,
        "open-horizon-register.json": horizon,
        "output-contract.json": output_contract,
    }
    for name, value in content_values.items():
        _json(content_root / name, value)

    npm_lock = {
        "name": "fixture",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": "fixture",
                "version": "1.0.0",
                "dependencies": {"alpha": "1.0.0", "@scope/gamma": "3.0.0"},
            },
            "node_modules/alpha": {"version": "1.0.0", "license": "MIT", "dependencies": {"beta": "2.0.0"}},
            "node_modules/beta": {"version": "2.0.0", "license": "Apache-2.0"},
            "node_modules/@scope/gamma": {"version": "3.0.0", "license": "MIT"},
        },
    }
    _json(repo / "master-reference" / "package-lock.json", npm_lock)
    _json(repo / "webapp" / "frontend" / "package-lock.json", npm_lock)
    _write(
        repo / "pyproject.toml",
        b'[project]\nname = "fixture-python"\nversion = "1.2.3"\ndependencies = ["alpha-py>=1,<2"]\n[project.optional-dependencies]\ndev = ["pytest>=8,<10"]\n',
    )
    _write(repo / "requirements.txt", b"alpha-py>=1,<2\n")
    _write(repo / "requirements-dev.txt", b"pytest>=8,<10\n")
    _write(repo / "webapp" / "requirements.txt", b"fastapi>=0.110,<1\n")
    _write(
        repo / "master-reference" / "requirements-release.txt",
        b"cryptography==49.0.0\njsonschema==4.26.0\npypdf==6.14.2\npytest==9.1.1\nreportlab==5.0.0\nruff==0.15.20\n",
    )
    _write(
        repo / "master-reference" / "governance" / "architecture.json",
        (MASTER_REFERENCE / "governance" / "architecture.json").read_bytes(),
    )
    _write(
        repo / "master-reference" / "release" / "pipeline.py",
        b'"""Synthetic tracked release-builder fixture."""\n',
    )
    schema_paths: list[str] = []
    for schema_path in sorted((MASTER_REFERENCE / "release" / "schemas").glob("*.json")):
        relative = f"master-reference/release/schemas/{schema_path.name}"
        _write(repo / relative, schema_path.read_bytes())
        schema_paths.append(relative)

    tracked_paths = [
        *(f"master-reference/content/{name}" for name in content_values),
        "master-reference/package-lock.json",
        "webapp/frontend/package-lock.json",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "master-reference/requirements-release.txt",
        "webapp/requirements.txt",
        "master-reference/governance/architecture.json",
        "master-reference/release/pipeline.py",
        *schema_paths,
    ]
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Atlas Fixture")
    _git(repo, "config", "user.email", "atlas-fixture@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "--all")
    commit_environment = os.environ.copy()
    commit_environment.update(
        {
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        }
    )
    _git(repo, "commit", "--quiet", "-m", "fixture", environment=commit_environment)
    commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    head_tree_oid = _git(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    stage_rows = [row for row in _git(repo, "ls-files", "--stage", "-z").split(b"\0") if row]
    git_entries: dict[str, tuple[str, str, int]] = {}
    index_rows: list[dict[str, object]] = []
    for row in stage_rows:
        metadata, raw_path = row.split(b"\t", 1)
        mode, blob_oid, stage_text = metadata.decode("ascii").split(" ")
        relative = raw_path.decode("utf-8")
        stage = int(stage_text)
        git_entries[relative] = (mode, blob_oid, stage)
        index_rows.append({"mode": mode, "blob_oid": blob_oid, "stage": stage, "path": relative})
    index_digest = digest_object(index_rows)
    assert set(tracked_paths) == set(git_entries)
    files = []
    for index, relative in enumerate(sorted(tracked_paths)):
        mode, blob_oid, stage = git_entries[relative]
        raw = _git(repo, "cat-file", "blob", blob_oid)
        files.append(
            {
                "id": f"file-{index}",
                "path": relative,
                "git_mode": mode,
                "git_blob_oid": blob_oid,
                "git_stage": stage,
                "content_source": "selected_commit_git_blob",
                "language": "json" if relative.endswith(".json") else "text",
                "roles": ["dataset"] if "/content/" in relative else ["manifest"],
                "privacy_exposure": "full",
                "parse_status": "parsed",
                "parser": "fixture",
                "parser_mode": "structured",
                "size_bytes": len(raw),
                "content_digest": sha256_bytes(raw),
                "line_count": max(1, len(raw.splitlines())),
                "nonblank_line_count": sum(1 for line in raw.splitlines() if line.strip()),
                "classification_errors": [],
                "unresolved_reasons": [],
            }
        )
    source_tree_digest = digest_object(
        [
            {
                "path": item["path"],
                "git_mode": item["git_mode"],
                "digest": item["content_digest"],
            }
            for item in sorted(files, key=lambda value: value["path"])
        ]
    )

    compiler = tmp_path / "compiler"
    records: dict[str, list[dict[str, object]]] = {name: [] for name in REQUIRED_GROUPS}
    records["files"] = files
    records["structural_entities"] = [
        {
            "id": f"root-{file_index}",
            "file_id": file_record["id"],
            "path": file_record["path"],
            "name": file_record["path"],
            "kind": "configuration_document",
            "entity_type": "structural_root_configuration_document",
            "root_scope": "parsed_source",
            "range": {
                "start_line": 1,
                "start_column": 0,
                "end_line": file_record["line_count"],
                "end_column": len(
                    _git(repo, "cat-file", "blob", str(file_record["git_blob_oid"]))
                    .decode("utf-8")
                    .splitlines()[-1]
                ),
            },
            "range_state": "exact_source_lines",
            "line_count": file_record["line_count"],
            "nonblank_line_count": file_record["nonblank_line_count"],
            "parser": file_record["parser"],
            "parser_mode": file_record["parser_mode"],
            "parser_version": file_record.get("parser_version"),
            "parser_owned": True,
            "language": file_record["language"],
            "roles": file_record["roles"],
            "source_basis": file_record["content_source"],
            "git_blob_oid": file_record["git_blob_oid"],
            "content_digest": file_record["content_digest"],
            "generation_provenance": {
                "state": "not_declared",
                "basis": "no_generated_role_or_generator_declaration",
                "generator_record_ids": [],
            },
            "extraction_disposition": "parser_structural_root",
            "explanation_depth": 1,
            "uncertainty": ["structural_root_does_not_establish_behavior_or_execution"],
            "unresolved_reasons": ["structural_root_does_not_establish_behavior_or_execution"],
        }
        for file_index, file_record in enumerate(files)
    ]
    roots_by_file = {
        root["file_id"]: root for root in records["structural_entities"]
    }
    records["lines"] = [
        {
            "id": f"line-{file_index}-{line_number}",
            "file_id": file_record["id"],
            "path": file_record["path"],
            "line": line_number,
            "explanation_depth": 1,
            "semantic_entity": roots_by_file[file_record["id"]]["id"],
            "structural_mapping_basis": "parser_structural_root",
        }
        for file_index, file_record in enumerate(files)
        for line_number, line in enumerate(
            _git(repo, "cat-file", "blob", str(file_record["git_blob_oid"])).splitlines(),
            start=1,
        )
        if line.strip()
    ]
    groups: dict[str, object] = {}
    for group_name in sorted(records):
        rows = records[group_name]
        chunks = []
        if rows:
            envelope = {
                "schema_version": "1.1.0",
                "record_type": group_name,
                "source_commit": commit,
                "source_tree_digest": source_tree_digest,
                "chunk_index": 0,
                "chunk_count": 1,
                "record_count": len(rows),
                "records_digest": digest_object([row["id"] for row in rows]),
                "records": rows,
            }
            relative = f"chunks/{group_name}/00000.json"
            raw = canonical_json(envelope)
            _write(compiler / relative, raw)
            chunks.append({"path": relative, "record_count": len(rows), "sha256": sha256_bytes(raw), "bytes": len(raw)})
        groups[group_name] = {
            "record_count": len(rows),
            "chunk_count": len(chunks),
            "records_digest": digest_object([row["id"] for row in rows]),
            "chunks": chunks,
        }

    architecture = {
        "schema_version": "1.1.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "status": "passed",
        "runtime_observed": False,
        "errors": [],
        "receipt_digest": "5" * 64,
    }
    completeness = {
        "id": "completeness-fixture",
        "schema_version": "1.1.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "tracked_worktree_dirty": False,
        "hard_failure": False,
        "fatal_errors": [],
        "parsing": {"status_counts": {"parsed": len(files)}, "lines_with_explicit_unresolved_reasons": 0},
        "graphify": {"available": True, "status": "current", "stale": False, "projected_nodes": 0, "projected_edges": 0},
        "architecture_conformance": architecture,
        "privacy": {"vault": "not_read", "client_state": "not_read", "network": "not_used"},
        "semantic_accounting": {
            "safe_parsed_sources": len(files),
            "structural_root_entities": len(records["structural_entities"]),
            "structurally_mapped_lines": len(records["lines"]),
            "gui_surface_records": 0,
            "gui_dossiers": 0,
        },
        "invariants": [
            {"name": "fixture-complete", "passed": True, "expected": 1, "actual": 1},
            {
                "name": "every_safe_parsed_source_has_one_structural_root",
                "passed": True,
                "expected": len(files),
                "actual": len(records["structural_entities"]),
            },
            {
                "name": "every_safe_line_structurally_mapped",
                "passed": True,
                "expected": len(records["lines"]),
                "actual": len(records["lines"]),
            },
            {
                "name": "every_gui_surface_has_standardized_evidence_honest_dossier",
                "passed": True,
                "expected": 0,
                "actual": 0,
            },
        ],
        "acceptance_gates": [
            {
                "name": name,
                "passed": name != "runtime_trace_evidence_joined_to_source_records",
                "expected": True,
                "actual": name != "runtime_trace_evidence_joined_to_source_records",
            }
            for name in sorted(REQUIRED_ACCEPTANCE_GATES)
        ],
    }
    graphify = {
        "schema_version": "1.1.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "available": True,
        "status": "current",
        "stale": False,
        "projected_nodes": 0,
        "projected_edges": 0,
    }
    completeness["graphify"] = graphify
    completeness_raw = canonical_json(completeness)
    graphify_raw = canonical_json(graphify)
    architecture_raw = canonical_json(architecture)
    _write(compiler / "completeness.json", completeness_raw)
    _write(compiler / "graphify-metadata.json", graphify_raw)
    _write(compiler / "architecture-conformance.json", architecture_raw)
    manifest = {
        "schema_version": "1.1.0",
        "status": "complete",
        "source_commit": commit,
        "head_tree_oid": head_tree_oid,
        "index_digest": index_digest,
        "source_tree_digest": source_tree_digest,
        "tracked_worktree_dirty": False,
        "release_class": "exact_commit",
        "chunk_size": 2000,
        "groups": groups,
        "completeness": {"path": "completeness.json", "sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)},
        "graphify_metadata": {"path": "graphify-metadata.json", "sha256": sha256_bytes(graphify_raw), "bytes": len(graphify_raw)},
        "architecture_conformance": {
            "path": "architecture-conformance.json",
            "sha256": sha256_bytes(architecture_raw),
            "bytes": len(architecture_raw),
        },
    }
    _json(compiler / "manifest.json", manifest)
    return repo, compiler


def _all_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_release_family_is_deterministic_and_explicitly_unsigned(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    first = tmp_path / "release-a"
    second = tmp_path / "release-b"
    manifest_a = build_release(repo, compiler, first, enhancement_gap="gap.one")
    manifest_b = build_release(repo, compiler, second, enhancement_gap="gap.one")

    assert manifest_a == manifest_b
    assert manifest_a["release_status"] == "unsigned_preview_incomplete"
    assert manifest_a["publication_status"] == "not_authorized"
    assert manifest_a["gates"]["pdf"] == "pending_external_renderer"
    assert manifest_a["gates"]["semantic_acceptance"] == "blocked"
    assert manifest_a["compiler"]["all_semantic_acceptance_gates_passed"] is False
    assert manifest_a["independent_verification_verdict"] == "BLOCK"
    assert manifest_a["gates"]["ed25519_signature"] == "pending_external_owner_key"
    assert _all_files(first) == _all_files(second)
    engineering = (first / "engineering-dossier.md").read_text(encoding="utf-8")
    engineering_text = " ".join(engineering.split())
    assert "does not attest whether the producer used a full or incremental rebuild" in engineering_text
    assert "run a full rebuild before relying on edge completeness" in engineering_text

    inventory = json.loads((first / "artifact-inventory.json").read_text(encoding="utf-8"))
    for artifact in inventory["artifacts"]:
        value = (first / artifact["path"]).read_bytes()
        assert len(value) == artifact["bytes"]
        assert hashlib.sha256(value).hexdigest() == artifact["sha256"]
    provenance = json.loads((first / "provenance.json").read_text(encoding="utf-8"))
    compiler_manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    subjects = {item["name"]: item["digest"]["sha256"] for item in provenance["subject"]}
    assert subjects["owner-handbook.md"] == hashlib.sha256((first / "owner-handbook.md").read_bytes()).hexdigest()
    assert all(value != compiler_manifest["source_tree_digest"] for value in subjects.values())
    assert provenance["predicate"]["runDetails"]["metadata"]["reproducible"] is False


def test_release_inputs_and_preservation_use_git_blobs_across_checkout_eol(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    lf_output = tmp_path / "release-lf"
    build_release(repo, compiler, lf_output)

    requirement_oid = _git(repo, "rev-parse", "HEAD:requirements.txt").decode("ascii").strip()
    canonical_requirement = _git(repo, "cat-file", "blob", requirement_oid)
    assert b"\r\n" not in canonical_requirement

    _git(repo, "config", "core.autocrlf", "true")
    tracked = [row.decode("utf-8") for row in _git(repo, "ls-files", "-z").split(b"\0") if row]
    for relative in tracked:
        (repo / relative).unlink()
    _git(repo, "checkout", "--", ".")
    assert b"\r\n" in (repo / "requirements.txt").read_bytes()
    assert not _git(repo, "status", "--porcelain=v1")

    crlf_output = tmp_path / "release-crlf"
    build_release(repo, compiler, crlf_output)
    assert _all_files(lf_output) == _all_files(crlf_output)

    with zipfile.ZipFile(crlf_output / "atlas-master-reference-preservation.zip") as archive:
        preserved = archive.read("dependency-inputs/requirements.txt")
    assert preserved == canonical_requirement
    provenance = json.loads((crlf_output / "provenance.json").read_text(encoding="utf-8"))
    material = next(
        item
        for item in provenance["predicate"]["buildDefinition"]["resolvedDependencies"]
        if item["uri"] == "requirements.txt"
    )
    assert material["digest"]["sha256"] == hashlib.sha256(canonical_requirement).hexdigest()


def test_archives_are_safe_sorted_fixed_epoch_and_preserve_compiler(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"
    build_release(repo, compiler, output)

    for archive_name in ("atlas-master-reference-offline.zip", "atlas-master-reference-preservation.zip"):
        with zipfile.ZipFile(output / archive_name) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            assert names == sorted(names)
            assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in infos)
            assert all(not name.startswith(("/", "\\")) and ".." not in Path(name).parts for name in names)
    with zipfile.ZipFile(output / "atlas-master-reference-preservation.zip") as archive:
        assert "compiler/manifest.json" in archive.namelist()
        assert "compiler/chunks/files/00000.json" in archive.namelist()
        assert "curated/capability-catalog.json" in archive.namelist()
        assert "dependency-inputs/master-reference/package-lock.json" in archive.namelist()


def test_sbom_has_locked_npm_transitives_and_honest_python_declarations(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"
    build_release(repo, compiler, output)
    sbom = json.loads((output / "bom.cdx.json").read_text(encoding="utf-8"))

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert any(component.get("purl") == "pkg:npm/alpha@1.0.0" for component in sbom["components"])
    assert any(component.get("purl") == "pkg:npm/beta@2.0.0" for component in sbom["components"])
    assert any(component.get("purl") == "pkg:npm/%40scope/gamma@3.0.0" for component in sbom["components"])
    python = [component for component in sbom["components"] if component.get("purl") == "pkg:pypi/alpha-py"]
    assert python
    assert all(
        {item["value"] for item in component["properties"] if item["name"] == "atlas:resolution"}
        == {"declared-unlocked"}
        for component in python
    )
    dependency_map = {item["ref"]: set(item["dependsOn"]) for item in sbom["dependencies"]}
    atlas_ref = sbom["metadata"]["component"]["bom-ref"]
    assert dependency_map[atlas_ref]
    python_root = next(
        component["bom-ref"]
        for component in sbom["components"]
        if component.get("name") == "fixture-python"
    )
    assert any(ref in dependency_map[python_root] for ref in (component["bom-ref"] for component in python))


def test_html_is_self_contained_and_csp_blocks_connections(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"
    build_release(repo, compiler, output)
    page = (output / "master-reference.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in page
    assert "<script src=" not in page
    assert "<link " not in page
    assert "fetch(" not in page
    compiler_manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    assert compiler_manifest["source_commit"] in page


def test_tampered_compiler_chunk_fails_before_output_creation(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    chunk = compiler / "chunks" / "files" / "00000.json"
    chunk.write_bytes(chunk.read_bytes() + b" ")
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="receipt mismatch"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_architecture_conformance_receipt_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["architecture_conformance"]
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="architecture conformance"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_structural_line_mapping_gate_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness["invariants"] = [
        item
        for item in completeness["invariants"]
        if item["name"] != "every_safe_line_structurally_mapped"
    ]
    completeness_raw = canonical_json(completeness)
    completeness_path.write_bytes(completeness_raw)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completeness"].update(
        {"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)}
    )
    manifest_path.write_bytes(canonical_json(manifest))

    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="structural line-mapping invariant"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_legacy_compiler_corpus_schema_is_rejected(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0.0"
    manifest_path.write_bytes(canonical_json(manifest))

    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="unsupported compiler schema"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_gui_dossier_invariant_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness["invariants"] = [
        item
        for item in completeness["invariants"]
        if item["name"]
        != "every_gui_surface_has_standardized_evidence_honest_dossier"
    ]
    completeness_raw = canonical_json(completeness)
    completeness_path.write_bytes(completeness_raw)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completeness"].update(
        {"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)}
    )
    manifest_path.write_bytes(canonical_json(manifest))

    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="GUI/root denominator is missing"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_duplicate_named_compiler_invariant_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness["invariants"].append(dict(completeness["invariants"][0]))
    completeness_raw = canonical_json(completeness)
    completeness_path.write_bytes(completeness_raw)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completeness"].update(
        {"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)}
    )
    manifest_path.write_bytes(canonical_json(manifest))

    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="invalid or duplicate name"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_structural_root_group_denominator_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["structural_entities"] = {
        "record_count": 0,
        "chunk_count": 0,
        "records_digest": digest_object([]),
        "chunks": [],
    }
    manifest_path.write_bytes(canonical_json(manifest))

    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="structural-entity group"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_source_binding_rejects_changed_curated_content(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    core = repo / "master-reference" / "content" / "atlas-core.json"
    data = json.loads(core.read_text(encoding="utf-8"))
    data["scope"] = "Changed after compilation."
    _json(core, data)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="tracked worktree changes"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_existing_nonempty_output_is_never_overwritten(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"
    output.mkdir()
    sentinel = output / "owner-data.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ReleaseError, match="must be empty"):
        build_release(repo, compiler, output)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_pdf_is_only_hash_bound_as_external_unreviewed_input(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"%PDF-1.7\nsk-proj-abcdefghijklmnopqrstuvwxyz123456\n%%EOF\n")
    output = tmp_path / "release"
    manifest = build_release(repo, compiler, output, pdf_path=pdf)
    gate = json.loads((output / "pdf-gate.json").read_text(encoding="utf-8"))
    assert manifest["release_status"] == "unsigned_preview_incomplete"
    assert gate["status"] == "externally_supplied_visual_review_pending"
    assert gate["binary_privacy_coverage"] == "blocked_external_binary_content_not_inspected"
    assert manifest["gates"]["generated_output_high_confidence_secret_scan"] == (
        "blocked_external_pdf_binary_not_content_inspected"
    )
    assert manifest["gates"]["binary_output_privacy_review"] == "blocked_external_pdf"
    assert gate["sha256"] == sha256_bytes(pdf.read_bytes())
    assert (output / "master-reference.pdf").read_bytes() == pdf.read_bytes()


def test_release_can_generate_source_bound_pdf_but_keeps_review_blocked(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"

    manifest = build_release(repo, compiler, output, generate_pdf=True)
    gate = json.loads((output / "pdf-gate.json").read_text(encoding="utf-8"))
    reader = pypdf.PdfReader(output / "master-reference.pdf")

    assert len(reader.pages) > 5
    assert gate["status"] == "generated_visual_review_pending"
    assert gate["independent_verification_verdict"] == "BLOCK"
    assert manifest["release_status"] == "unsigned_preview_incomplete"
    assert manifest["independent_verification_verdict"] == "BLOCK"


def test_external_ed25519_hooks_sign_verify_and_detect_tamper(tmp_path: Path) -> None:
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    asymmetric = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    # Ephemeral test-only material exercises the hook; production tooling has no
    # key-generation API and consumes only owner-supplied external paths.
    key = asymmetric.Ed25519PrivateKey.generate()
    private_path = tmp_path / "external-test-private.pem"
    public_path = tmp_path / "trusted-test-public.pem"
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    repo, compiler = _fixture_repo(tmp_path)
    release_dir = tmp_path / "release"
    build_release(repo, compiler, release_dir)
    manifest_path = release_dir / "release-manifest.json"
    signature_path = release_dir / "release-manifest.sig.json"

    envelope = sign_manifest(manifest_path, private_path, signature_path)
    result = verify_manifest(manifest_path, signature_path, public_path)
    assert envelope["algorithm"] == "Ed25519"
    assert result["verified"] is True
    assert result["artifacts_verified"] > 10

    (release_dir / "owner-handbook.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="artifact receipt mismatch"):
        verify_manifest(manifest_path, signature_path, public_path)


def test_unsigned_family_integrity_verifier_is_explicitly_not_signature_trust(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    release_dir = tmp_path / "release"
    build_release(repo, compiler, release_dir)

    result = verify_artifact_family(release_dir / "release-manifest.json")
    assert result["artifacts_verified"] > 10
    assert result["release_status"] == "unsigned_preview_incomplete"

    (release_dir / "agent-pack.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="artifact receipt mismatch"):
        verify_artifact_family(release_dir / "release-manifest.json")


def test_stale_clean_head_is_rejected_before_output(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _git(repo, "commit", "--allow-empty", "--quiet", "-m", "newer source state")
    output = tmp_path / "release"

    with pytest.raises(ReleaseError, match="HEAD differs"):
        build_release(repo, compiler, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "relative",
    [
        "master-reference/governance/architecture.json",
        "master-reference/release/pipeline.py",
    ],
)
def test_full_exposure_architecture_and_builder_bytes_cannot_evade_binding(
    tmp_path: Path,
    relative: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _git(repo, "update-index", "--assume-unchanged", relative)
    path = repo / relative
    path.write_bytes(path.read_bytes() + b"\n")
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=no") == b""
    output = tmp_path / "release"

    with pytest.raises(ReleaseError, match="full-exposure file differs from compiler source"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_output_contract_mismatch_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    monkeypatch.setattr(
        release_pipeline,
        "PLANNED_ALWAYS_MEMBERS",
        release_pipeline.PLANNED_ALWAYS_MEMBERS - {"owner-handbook.md"},
    )
    output = tmp_path / "release"

    with pytest.raises(ReleaseError, match="output contract differs"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_output_contract_schema_fails_closed(tmp_path: Path) -> None:
    repo, _compiler = _fixture_repo(tmp_path)
    invalid = {
        "schema_version": "1.0.0",
        "id": "invalid",
        "catalog_version": "fixture",
        "purpose": "negative test",
        "members": [{"id": "missing-required-fields"}],
        "external_signature_member": "release-manifest.sig.json",
        "disclosure": "negative test",
    }

    with pytest.raises(RuntimeError, match="fails output-contract schema"):
        validate_release_object(repo, "output-contract", invalid)


def test_late_member_failure_is_atomic_and_preserves_existing_empty_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    output = tmp_path / "release"
    output.mkdir()
    original = release_pipeline._artifact

    def inject_extra(root: Path, relative: str, value: bytes, role: str) -> dict[str, object]:
        item = original(root, relative, value, role)
        if relative == "release-manifest.json":
            (root / "undeclared-late.bin").write_bytes(b"late")
        return item

    monkeypatch.setattr(release_pipeline, "_artifact", inject_extra)
    with pytest.raises(ReleaseError, match="emitted release members differ"):
        build_release(repo, compiler, output)

    assert output.is_dir()
    assert not any(output.iterdir())
    assert not list(tmp_path.glob(".release.building-*"))


def test_integrity_verifier_rejects_undeclared_sibling(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    release_dir = tmp_path / "release"
    build_release(repo, compiler, release_dir)
    (release_dir / "undeclared.txt").write_text("not in contract", encoding="utf-8")

    with pytest.raises(RuntimeError, match="undeclared sibling"):
        verify_artifact_family(release_dir / "release-manifest.json")


def test_integrity_verifier_rejects_inventory_manifest_divergence(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    release_dir = tmp_path / "release"
    build_release(repo, compiler, release_dir)
    inventory_path = release_dir / "artifact-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["artifacts"] = inventory["artifacts"][1:]
    inventory_raw = canonical_json(inventory)
    inventory_path.write_bytes(inventory_raw)
    manifest_path = release_dir / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = next(value for value in manifest["artifacts"] if value["path"] == "artifact-inventory.json")
    item["sha256"] = sha256_bytes(inventory_raw)
    item["bytes"] = len(inventory_raw)
    manifest_path.write_bytes(canonical_json(manifest))

    with pytest.raises(RuntimeError, match="inventory receipts differ"):
        verify_artifact_family(manifest_path)


def test_sbom_and_preservation_denominators_are_explicit(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    release_dir = tmp_path / "release"
    manifest = build_release(repo, compiler, release_dir)
    sbom = json.loads((release_dir / "bom.cdx.json").read_text(encoding="utf-8"))

    for component in sbom["components"]:
        properties = {item["name"]: item["value"] for item in component["properties"]}
        assert properties["atlas:licenseStatus"] in {"declared", "unknown"}
        assert properties["atlas:vulnerabilityStatus"] == "not_assessed"
    denominators = {item["name"]: item["value"] for item in sbom["properties"]}
    assert int(denominators["atlas:componentDenominator"]) == len(sbom["components"])
    assert int(denominators["atlas:vulnerabilityNotAssessed"]) == len(sbom["components"])
    assert denominators["atlas:vulnerabilityAssessed"] == "0"
    coverage = json.loads((release_dir / "preservation-coverage.json").read_text(encoding="utf-8"))
    assert coverage["gate"] == "BLOCK"
    assert coverage["missing_required_for_recovery_claim"]
    assert manifest["gates"]["preservation_recovery"].startswith("blocked_")
    attestation = json.loads((release_dir / "family-attestation.json").read_text(encoding="utf-8"))
    assert set(attestation["output_contract"]["expected_members"]) == {
        path.name for path in release_dir.iterdir() if path.is_file()
    }
