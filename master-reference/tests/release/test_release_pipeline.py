from __future__ import annotations

import copy
import hashlib
import binascii
import json
import os
import re
import subprocess
import struct
import sys
import traceback
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from release.compiler_bundle import REQUIRED_ACCEPTANCE_GATES, REQUIRED_GROUPS  # noqa: E402
from compiler import compile_repository  # noqa: E402
from compiler import binary_review as binary_review_module  # noqa: E402
from compiler.binary_review import binary_set_digest, inspect_png  # noqa: E402
from compiler.graphify import (  # noqa: E402
    GRAPHIFY_BASE_UNRESOLVED_REASONS,
    GRAPHIFY_HYPEREDGE_REASON_ABSENT,
    OPAQUE_IDENTIFIER_POLICY,
)
from compiler.binary_review import unavailable_summary as unavailable_binary_review_summary  # noqa: E402
from governance.consequential_claims import (  # noqa: E402
    CONTENT_PATHS as CONSEQUENTIAL_CLAIM_CONTENT_PATHS,
    unavailable_bounded_curated_claim_summary,
)
from release.model import (  # noqa: E402
    ReleaseInputError,
    canonical_json,
    digest_object,
    sha256_bytes,
    stable_id,
)
import release.pipeline as release_pipeline  # noqa: E402
import release.compiler_bundle as compiler_bundle  # noqa: E402
from release.pipeline import ReleaseError, build_release  # noqa: E402
from release.sbom import NPM_LOCKFILES, PYTHON_DECLARATIONS, build_cyclonedx  # noqa: E402
from release.signing import sign_manifest, verify_artifact_family, verify_manifest  # noqa: E402
from release.schema_validation import validate_release_object  # noqa: E402


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _json(path: Path, value: object) -> None:
    _write(path, canonical_json(value))


def _formatted_exception(failure: pytest.ExceptionInfo[BaseException]) -> str:
    return "".join(traceback.format_exception(failure.type, failure.value, failure.tb))


def _one_pixel_png(*, compression_level: int = -1) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    scanline = b"\x00\x00\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanline, level=compression_level))
        + chunk(b"IEND", b"")
    )


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


def _declared_claim_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "declared-claim-repo"
    repo.mkdir()
    _write(repo / "README.md", b"# Consequential claim fixture\n")
    for name in (
        "atlas-core.json",
        "capability-catalog.json",
        "delivery-governance.json",
        "open-horizon-register.json",
        "output-contract.json",
    ):
        _write(
            repo / "master-reference" / "content" / name,
            (MASTER_REFERENCE / "content" / name).read_bytes(),
        )
    _write(
        repo / "master-reference" / "governance" / "consequential-claim-contract.json",
        (MASTER_REFERENCE / "governance" / "consequential-claim-contract.json").read_bytes(),
    )
    _json(
        repo / "master-reference" / "governance" / "architecture.json",
        {
            "schema_version": "2.0.0",
            "python_import_roots": [],
            "internal_module_prefixes": [],
            "components": [
                {
                    "id": "repository",
                    "paths": ["README.md", "master-reference/"],
                }
            ],
            "exclusions": [],
            "allowed_edges": [],
            "forbidden_edges": [],
            "runtime_phases": [{"id": "compile", "order": 1, "required": False}],
            "synthetic_runtime_traces": [
                {
                    "id": "fixture",
                    "events": [
                        {
                            "phase": "compile",
                            "status": "passed",
                            "receipt_id": "synthetic:fixture:compile",
                        }
                    ],
                }
            ],
        },
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "user.name", "Atlas Test")
    _git(repo, "config", "user.email", "atlas@example.invalid")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-qm", "declared claim fixture")
    return repo


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
    # The generated-PDF path consumes the complete, fail-closed Horizon owner.
    # Reuse its exact tracked shape instead of maintaining an impossible partial
    # fixture that can mask stale renderer field names or safety fallbacks.
    horizon = json.loads((MASTER_REFERENCE / "content" / "open-horizon-register.json").read_text(encoding="utf-8"))
    output_contract = json.loads((MASTER_REFERENCE / "content" / "output-contract.json").read_text(encoding="utf-8"))
    content_values = {
        "atlas-core.json": core,
        "capability-catalog.json": catalog,
        "delivery-governance.json": governance,
        "open-horizon-register.json": horizon,
        "output-contract.json": output_contract,
    }
    for name, value in content_values.items():
        if name == "open-horizon-register.json":
            _write(content_root / name, (MASTER_REFERENCE / "content" / name).read_bytes())
        else:
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
                "devDependencies": {"devtool": "4.0.0"},
            },
            "node_modules/alpha": {"version": "1.0.0", "license": "MIT", "dependencies": {"beta": "2.0.0"}},
            "node_modules/beta": {"version": "2.0.0", "license": "Apache-2.0"},
            "node_modules/@scope/gamma": {"version": "3.0.0", "license": "MIT"},
            "node_modules/devtool": {
                "version": "4.0.0",
                "dev": True,
                "dependencies": {"dev-leaf": "5.0.0"},
                "peerDependencies": {"optional-peer": "^6.0.0"},
                "peerDependenciesMeta": {"optional-peer": {"optional": True}},
            },
            "node_modules/dev-leaf": {"version": "5.0.0", "dev": True},
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
        repo / "master-reference" / "governance" / "rendered-sink-lineage-contract.json",
        (MASTER_REFERENCE / "governance" / "rendered-sink-lineage-contract.json").read_bytes(),
    )
    _write(
        repo / "master-reference" / "schema" / "rendered-sink-lineage.schema.json",
        (MASTER_REFERENCE / "schema" / "rendered-sink-lineage.schema.json").read_bytes(),
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
        "master-reference/governance/rendered-sink-lineage-contract.json",
        "master-reference/schema/rendered-sink-lineage.schema.json",
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
                "id": f"urn:atlas:file:{index:024x}",
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
            "id": f"urn:atlas:structural-root:{file_index:024x}",
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
                    _git(repo, "cat-file", "blob", str(file_record["git_blob_oid"])).decode("utf-8").splitlines()[-1]
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
    roots_by_file = {root["file_id"]: root for root in records["structural_entities"]}
    line_records: list[dict[str, object]] = []
    for file_index, file_record in enumerate(files):
        source_lines = _git(repo, "cat-file", "blob", str(file_record["git_blob_oid"])).splitlines()
        for line_number, line in enumerate(source_lines, start=1):
            if not line.strip():
                continue
            line_id = hashlib.sha256(f"{file_index}:{line_number}".encode("ascii")).hexdigest()[:24]
            line_digest = sha256_bytes(line)
            root_id = roots_by_file[file_record["id"]]["id"]
            line_records.append(
                {
                    "id": f"urn:atlas:line:{line_id}",
                    "file_id": file_record["id"],
                    "path": file_record["path"],
                    "line": line_number,
                    "language": file_record["language"],
                    "syntax_kind": "source_line",
                    "depth": 0,
                    "text_digest": line_digest,
                    "line_digest": line_digest,
                    "text_bytes": len(line),
                    "source_commit": commit,
                    "line_number": line_number,
                    "semantic_entity": root_id,
                    "owner": root_id,
                    "structural_mapping_basis": "parser_structural_root",
                    "behavior_group": [],
                    "inputs_and_outputs": {},
                    "claims_influenced": [],
                    "callers_and_dependencies": [],
                    "tests_covering_it": [],
                    "runtime_trace_state": "not_observed",
                    "GUI_or_artifact_consumers": [],
                    "security_and_privacy_effect": {},
                    "current_or_historical": "current",
                    "explanation_depth": 1,
                    "unresolved_reasons": ["behavior_not_semantically_explained"],
                }
            )
    records["lines"] = line_records
    groups: dict[str, object] = {}
    for group_name in sorted(records):
        rows = sorted(records[group_name], key=lambda row: str(row["id"]))
        records[group_name] = rows
        chunks = []
        if rows:
            envelope = {
                "schema_version": "1.2.0",
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
        "schema_version": "1.2.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "status": "passed",
        "runtime_observed": False,
        "errors": [],
        "receipt_digest": "5" * 64,
    }
    completeness = {
        "id": "completeness-fixture",
        "schema_version": "1.2.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "tracked_worktree_dirty": False,
        "hard_failure": False,
        "fatal_errors": [],
        "parsing": {"status_counts": {"parsed": len(files)}, "lines_with_explicit_unresolved_reasons": 0},
        "graphify": {
            "available": True,
            "status": "current",
            "stale": False,
            "built_at_commit": commit,
            "total_nodes": 0,
            "projected_nodes": 0,
            "excluded_nodes": 0,
            "total_edges": 0,
            "projected_edges": 0,
            "excluded_edges": 0,
            "excluded_node_dispositions": [],
            "excluded_edge_dispositions": [],
            "excluded_edge_endpoint_dispositions": {},
            "node_disposition_counts": {
                "retained": 0,
                "excluded_unsafe_source": 0,
                "excluded_untracked_or_private": 0,
            },
            "identifier_projection_policy": OPAQUE_IDENTIFIER_POLICY,
            "node_identifier_disposition_counts": {
                "total": 0,
                "projected_repository_relative": 0,
                "excluded_opaque": 0,
                "raw_published": 0,
            },
        },
        "architecture_conformance": architecture,
        "privacy": {
            "vault": "not_read",
            "client_state": "not_read",
            "network": "not_used",
            "binary_payload_scan": {
                **unavailable_binary_review_summary([], status="absent"),
                "inventory_only_files": 0,
                "format_aware_or_manual_review_receipt": "absent",
                "claim": "Synthetic fixture has no tracked binary review receipt.",
            },
        },
        "semantic_accounting": {
            "safe_parsed_sources": len(files),
            "structural_root_entities": len(records["structural_entities"]),
            "structurally_mapped_lines": len(records["lines"]),
            "gui_surface_records": 0,
            "gui_dossiers": 0,
            "consequential_claim_denominator_state": "not_declared",
        },
        "consequential_claim_denominator": unavailable_bounded_curated_claim_summary(
            source_commit=commit,
            source_tree_digest=source_tree_digest,
        ),
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
                "passed": name
                not in {
                    "every_binary_has_format_aware_privacy_review",
                    "runtime_trace_evidence_joined_to_source_records",
                    "consequential_claim_denominator_closed",
                },
                "expected": 0 if name == "every_binary_has_format_aware_privacy_review" else True,
                "actual": (
                    0
                    if name == "every_binary_has_format_aware_privacy_review"
                    else name
                    not in {
                        "runtime_trace_evidence_joined_to_source_records",
                        "consequential_claim_denominator_closed",
                    }
                ),
            }
            for name in sorted(REQUIRED_ACCEPTANCE_GATES)
        ],
    }
    graphify = {
        "schema_version": "1.2.0",
        "source_commit": commit,
        "source_tree_digest": source_tree_digest,
        "available": True,
        "status": "current",
        "source": "graphify-out/graph.json",
        "source_bytes": 2,
        "source_digest": "6" * 64,
        "report_available": False,
        "stale": False,
        "built_at_commit": commit,
        "total_nodes": 0,
        "projected_nodes": 0,
        "excluded_nodes": 0,
        "total_edges": 0,
        "projected_edges": 0,
        "excluded_edges": 0,
        "total_hyperedges": 0,
        "excluded_node_dispositions": [],
        "excluded_edge_dispositions": [],
        "excluded_edge_endpoint_dispositions": {},
        "all_edge_modes": {},
        "projected_edge_modes": {},
        "node_origins": {},
        "excluded_nodes_unsafe_source": 0,
        "excluded_nodes_untracked_or_private": 0,
        "node_disposition_counts": {
            "retained": 0,
            "excluded_unsafe_source": 0,
            "excluded_untracked_or_private": 0,
        },
        "identifier_projection_policy": OPAQUE_IDENTIFIER_POLICY,
        "node_identifier_disposition_counts": {
            "total": 0,
            "projected_repository_relative": 0,
            "excluded_opaque": 0,
            "raw_published": 0,
        },
        "total_communities": 0,
        "projected_communities": 0,
        "excluded_communities": 0,
        "all_community_ids": [],
        "projected_community_ids": [],
        "excluded_community_ids": [],
        "partial_community_ids": [],
        "community_status_counts": {
            "projected_complete": 0,
            "projected_partial": 0,
            "excluded": 0,
        },
        "community_dispositions": [],
        "projection_policy": "tracked_full_exposure_files_only",
        "unresolved_reasons": [
            GRAPHIFY_BASE_UNRESOLVED_REASONS[0],
            GRAPHIFY_HYPEREDGE_REASON_ABSENT,
            *GRAPHIFY_BASE_UNRESOLVED_REASONS[1:],
        ],
    }
    completeness["graphify"] = graphify
    completeness_raw = canonical_json(completeness)
    graphify_raw = canonical_json(graphify)
    architecture_raw = canonical_json(architecture)
    _write(compiler / "completeness.json", completeness_raw)
    _write(compiler / "graphify-metadata.json", graphify_raw)
    _write(compiler / "architecture-conformance.json", architecture_raw)
    manifest = {
        "schema_version": "1.2.0",
        "status": "complete",
        "source_commit": commit,
        "head_tree_oid": head_tree_oid,
        "index_digest": index_digest,
        "source_tree_digest": source_tree_digest,
        "tracked_worktree_dirty": False,
        "release_class": "exact_commit",
        "chunk_size": 2000,
        "groups": groups,
        "completeness": {
            "path": "completeness.json",
            "sha256": sha256_bytes(completeness_raw),
            "bytes": len(completeness_raw),
        },
        "graphify_metadata": {
            "path": "graphify-metadata.json",
            "sha256": sha256_bytes(graphify_raw),
            "bytes": len(graphify_raw),
        },
        "architecture_conformance": {
            "path": "architecture-conformance.json",
            "sha256": sha256_bytes(architecture_raw),
            "bytes": len(architecture_raw),
        },
    }
    _json(compiler / "manifest.json", manifest)
    return repo, compiler


def _replace_graph_fixture(
    compiler: Path,
    *,
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]] | None = None,
    graphify_extra: dict[str, object] | None = None,
) -> None:
    edges = [] if edges is None else edges
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    for group_name, rows in (("graph_nodes", nodes), ("graph_edges", edges)):
        chunks: list[dict[str, object]] = []
        if rows:
            envelope = {
                "schema_version": "1.2.0",
                "record_type": group_name,
                "source_commit": manifest["source_commit"],
                "source_tree_digest": manifest["source_tree_digest"],
                "chunk_index": 0,
                "chunk_count": 1,
                "record_count": len(rows),
                "records_digest": digest_object([row["id"] for row in rows]),
                "records": rows,
            }
            relative = f"chunks/{group_name}/00000.json"
            raw = canonical_json(envelope)
            _write(compiler / relative, raw)
            chunks.append(
                {
                    "path": relative,
                    "record_count": len(rows),
                    "sha256": sha256_bytes(raw),
                    "bytes": len(raw),
                }
            )
        manifest["groups"][group_name] = {
            "record_count": len(rows),
            "chunk_count": len(chunks),
            "records_digest": digest_object([row["id"] for row in rows]),
            "chunks": chunks,
        }

    graphify = json.loads((compiler / "graphify-metadata.json").read_text(encoding="utf-8"))
    node_origin_counts: dict[str, int] = {}
    projected_community_node_counts: dict[int, int] = {}
    for node in nodes:
        origin = node.get("origin")
        if isinstance(origin, str):
            node_origin_counts[origin] = node_origin_counts.get(origin, 0) + 1
        community = node.get("community")
        if type(community) is int:
            projected_community_node_counts[community] = projected_community_node_counts.get(community, 0) + 1
    projected_edge_modes: dict[str, int] = {}
    for edge in edges:
        mode = edge.get("extraction_mode")
        if isinstance(mode, str):
            projected_edge_modes[mode] = projected_edge_modes.get(mode, 0) + 1
    projected_community_ids = sorted(projected_community_node_counts)
    community_dispositions = [
        {
            "community": community,
            "status": "projected_complete",
            "total_nodes": retained_nodes,
            "retained_nodes": retained_nodes,
            "excluded_nodes": 0,
        }
        for community, retained_nodes in sorted(projected_community_node_counts.items())
    ]
    graphify.update(
        {
            "total_nodes": len(nodes),
            "projected_nodes": len(nodes),
            "excluded_nodes": 0,
            "total_edges": len(edges),
            "projected_edges": len(edges),
            "excluded_edges": 0,
            "excluded_node_dispositions": [],
            "excluded_edge_dispositions": [],
            "excluded_edge_endpoint_dispositions": {},
            "all_edge_modes": dict(sorted(projected_edge_modes.items())),
            "projected_edge_modes": dict(sorted(projected_edge_modes.items())),
            "node_origins": dict(sorted(node_origin_counts.items())),
            "excluded_nodes_unsafe_source": 0,
            "excluded_nodes_untracked_or_private": 0,
            "node_disposition_counts": {
                "retained": len(nodes),
                "excluded_unsafe_source": 0,
                "excluded_untracked_or_private": 0,
            },
            "identifier_projection_policy": OPAQUE_IDENTIFIER_POLICY,
            "node_identifier_disposition_counts": {
                "total": len(nodes),
                "projected_repository_relative": len(nodes),
                "excluded_opaque": 0,
                "raw_published": 0,
            },
            "total_communities": len(projected_community_ids),
            "projected_communities": len(projected_community_ids),
            "excluded_communities": 0,
            "all_community_ids": projected_community_ids,
            "projected_community_ids": projected_community_ids,
            "excluded_community_ids": [],
            "partial_community_ids": [],
            "community_status_counts": {
                "projected_complete": len(projected_community_ids),
                "projected_partial": 0,
                "excluded": 0,
            },
            "community_dispositions": community_dispositions,
        }
    )
    if graphify_extra:
        graphify.update(graphify_extra)
    completeness = json.loads((compiler / "completeness.json").read_text(encoding="utf-8"))
    completeness["graphify"] = graphify
    graphify_raw = canonical_json(graphify)
    completeness_raw = canonical_json(completeness)
    _write(compiler / "graphify-metadata.json", graphify_raw)
    _write(compiler / "completeness.json", completeness_raw)
    manifest["graphify_metadata"] = {
        "path": "graphify-metadata.json",
        "sha256": sha256_bytes(graphify_raw),
        "bytes": len(graphify_raw),
    }
    manifest["completeness"] = {
        "path": "completeness.json",
        "sha256": sha256_bytes(completeness_raw),
        "bytes": len(completeness_raw),
    }
    _json(compiler / "manifest.json", manifest)


def _rewrite_chunk(
    compiler: Path,
    group_name: str,
    transform: Callable[[dict[str, object]], None],
) -> None:
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_receipt = manifest["groups"][group_name]["chunks"][0]
    chunk_path = compiler / chunk_receipt["path"]
    envelope = json.loads(chunk_path.read_text(encoding="utf-8"))
    transform(envelope)
    raw = canonical_json(envelope)
    _write(chunk_path, raw)
    chunk_receipt["sha256"] = sha256_bytes(raw)
    chunk_receipt["bytes"] = len(raw)
    _json(manifest_path, manifest)


def _replace_group_fixture(
    compiler: Path,
    group_name: str,
    rows: list[dict[str, object]],
) -> None:
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks: list[dict[str, object]] = []
    if rows:
        envelope = {
            "schema_version": "1.2.0",
            "record_type": group_name,
            "source_commit": manifest["source_commit"],
            "source_tree_digest": manifest["source_tree_digest"],
            "chunk_index": 0,
            "chunk_count": 1,
            "record_count": len(rows),
            "records_digest": digest_object([row["id"] for row in rows]),
            "records": rows,
        }
        relative = f"chunks/{group_name}/00000.json"
        raw = canonical_json(envelope)
        _write(compiler / relative, raw)
        chunks.append(
            {
                "path": relative,
                "record_count": len(rows),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
            }
        )
    manifest["groups"][group_name] = {
        "record_count": len(rows),
        "chunk_count": len(chunks),
        "records_digest": digest_object([row["id"] for row in rows]),
        "chunks": chunks,
    }
    _json(manifest_path, manifest)


def _replace_group_chunk_fixture(
    compiler: Path,
    group_name: str,
    chunk_rows: list[list[dict[str, object]]],
) -> None:
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    flattened = [row for rows in chunk_rows for row in rows]
    chunks: list[dict[str, object]] = []
    for index, rows in enumerate(chunk_rows):
        envelope = {
            "schema_version": "1.2.0",
            "record_type": group_name,
            "source_commit": manifest["source_commit"],
            "source_tree_digest": manifest["source_tree_digest"],
            "chunk_index": index,
            "chunk_count": len(chunk_rows),
            "record_count": len(rows),
            "records_digest": digest_object([row["id"] for row in rows]),
            "records": rows,
        }
        relative = f"chunks/{group_name}/{index:05d}.json"
        raw = canonical_json(envelope)
        _write(compiler / relative, raw)
        chunks.append(
            {
                "path": relative,
                "record_count": len(rows),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
            }
        )
    manifest["groups"][group_name] = {
        "record_count": len(flattened),
        "chunk_count": len(chunks),
        "records_digest": digest_object([row["id"] for row in flattened]),
        "chunks": chunks,
    }
    _json(manifest_path, manifest)


def _graph_node(
    compiler: Path,
    *,
    label: str = "derived",
    graphify_id: str | None = None,
) -> dict[str, object]:
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    files_receipt = manifest["groups"]["files"]["chunks"][0]
    files_envelope = json.loads((compiler / files_receipt["path"]).read_text(encoding="utf-8"))
    file_record = files_envelope["records"][0]
    if graphify_id is None:
        graphify_id = digest_object(
            [
                "repository-relative-graph-node",
                file_record["path"],
                "L1",
                "0",
            ]
        )
    return {
        "id": stable_id("graph-node", manifest["source_commit"], graphify_id),
        "graphify_id": graphify_id,
        "coordinate_occurrence": 0,
        "file_id": file_record["id"],
        "source_file": file_record["path"],
        "source_location": "L1",
        "label": label if label != "derived" else f"{file_record['path']}:L1#1",
        "file_type": "document",
        "language": "json",
        "kind": "file",
        "community": 1,
        "origin": "ast",
        "extraction_mode": "extracted",
        "entity_type": "graph_node_file",
        "unresolved_reasons": [
            "graphify_node_label_derived_from_repository_relative_coordinate",
        ],
    }


def _graph_edge(
    compiler: Path,
    node: dict[str, object],
    *,
    extraction_mode: str = "extracted",
) -> dict[str, object]:
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    coordinate: tuple[object, ...] = (
        node["id"],
        node["id"],
        "calls",
        "",
        "",
        extraction_mode,
        "none",
    )
    return {
        "id": stable_id("graph-edge", manifest["source_commit"], *coordinate, 0),
        "source": node["id"],
        "target": node["id"],
        "relation": "calls",
        "coordinate_occurrence": 0,
        "source_file": None,
        "source_location": "",
        "extraction_mode": extraction_mode,
        "confidence": None,
        "entity_type": "graph_edge",
        "unresolved_reasons": (
            []
            if extraction_mode in {"extracted", "inferred"}
            else ["graphify_confidence_mode_undisclosed_or_ambiguous"]
        ),
    }


def _all_files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


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
    assert manifest_a["gates"]["dependency_vulnerability_assessment"] == (
        "blocked_external_current_advisory_applicability_review_required"
    )
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


def test_compiler_bundle_preserves_pending_binary_review_and_rejects_custody_or_digest_tamper(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "binary-review-repo"
    repo.mkdir()
    payload = _one_pixel_png()
    _write(repo / "README.md", b"# Binary review fixture\n")
    _write(repo / "docs" / "card.png", payload)
    _json(
        repo / "master-reference" / "governance" / "architecture.json",
        {
            "schema_version": "2.0.0",
            "python_import_roots": [],
            "internal_module_prefixes": [],
            "components": [
                {
                    "id": "repository",
                    "paths": ["README.md", "docs/", "master-reference/"],
                }
            ],
            "exclusions": [],
            "allowed_edges": [],
            "forbidden_edges": [],
            "runtime_phases": [{"id": "compile", "order": 1, "required": False}],
            "synthetic_runtime_traces": [
                {
                    "id": "fixture",
                    "events": [
                        {
                            "phase": "compile",
                            "status": "passed",
                            "receipt_id": "synthetic:fixture:compile",
                        }
                    ],
                }
            ],
        },
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "user.name", "Atlas Test")
    _git(repo, "config", "user.email", "atlas@example.invalid")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-qm", "binary fixture")
    review_basis_commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    git_blob_oid = _git(repo, "rev-parse", f"{review_basis_commit}:docs/card.png").decode("ascii").strip()
    raw_digest = hashlib.sha256(payload).hexdigest()
    record = {
        "path": "docs/card.png",
        "git_blob_oid": git_blob_oid,
        "raw_sha256": raw_digest,
        "raw_bytes": len(payload),
        "media_type": "image/png",
        "format": "png",
        "automated_format_evidence": inspect_png(payload),
        "independent_review": {
            "reviewer_kind": "independent_agent",
            "reviewer_role": "binary_privacy_verifier",
            "independent_from_proposer": True,
            "review_scope": "rendered_pixels_and_context",
            "evidence_references": [
                f"decoded-rgba-sha256:{hashlib.sha256(bytes((0, 0, 0, 255))).hexdigest()}",
                "privacy-scan:forbidden-local-generic-identities",
                "visual-review:exact-rendered-pixels",
            ],
            "verdict": "pass",
        },
    }
    receipt = {
        "schema_version": "tracked-binary-review/1",
        "receipt_kind": "tracked_repository_binary_privacy_review",
        "review_basis_commit": review_basis_commit,
        "binary_set_digest": binary_set_digest([record]),
        "records": [record],
    }
    receipt_path = repo / "master-reference" / "governance" / "tracked-binary-review.json"
    _write(receipt_path, canonical_json(receipt))
    _git(repo, "add", receipt_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-qm", "independent binary review receipt")

    compiler_output = tmp_path / "compiler-output"
    compile_repository(repo, compiler_output)
    bundle = compiler_bundle.load_compiler_bundle(
        compiler_output,
        repository_root=repo,
    )

    scan = bundle.completeness["privacy"]["binary_payload_scan"]
    binary_gate = next(
        gate
        for gate in bundle.completeness["acceptance_gates"]
        if gate["name"] == "every_binary_has_format_aware_privacy_review"
    )
    assert scan["status"] == "incomplete"
    assert scan["expected_files"] == 1
    assert scan["automated_format_passed_files"] == 1
    assert scan["automated_format_pending_files"] == 0
    assert scan["claimed_independent_contextual_passed_files"] == 1
    assert scan["independent_contextual_passed_files"] == 0
    assert scan["accepted_files"] == 0
    assert scan["error_codes"] == ["binary_review_reviewer_authentication_pending"]
    assert binary_gate == {
        "name": "every_binary_has_format_aware_privacy_review",
        "passed": False,
        "expected": 1,
        "actual": 0,
    }
    assert bundle.records["binaries"][0]["content_digest"] is None
    assert bundle.records["binaries"][0]["privacy_exposure"] == "metadata_only"
    assert all(row["path"] != "docs/card.png" for row in bundle.records["source_text"])

    completeness_path = compiler_output / "completeness.json"
    manifest_path = compiler_output / "manifest.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def rewrite_completeness(value: dict[str, object]) -> None:
        raw = canonical_json(value)
        _write(completeness_path, raw)
        manifest["completeness"]["sha256"] = sha256_bytes(raw)
        manifest["completeness"]["bytes"] = len(raw)
        _write(manifest_path, canonical_json(manifest))

    original_completeness = json.loads(json.dumps(completeness))
    completeness["privacy"]["binary_payload_scan"]["reviewer_custody"] = {
        "status": "authenticated",
        "required_mechanism": "invented-string",
        "trusted_public_key_configured": True,
        "detached_signature_present": True,
        "detached_signature_verified": True,
        "authenticated_reviewer_kind": "independent_agent",
        "authenticated_files": 1,
        "receipt_claims_trusted": True,
    }
    rewrite_completeness(completeness)
    with pytest.raises(
        ReleaseInputError,
        match="compiler binary-review summary is absent or malformed",
    ):
        compiler_bundle.load_compiler_bundle(
            compiler_output,
            repository_root=repo,
        )

    completeness = original_completeness
    completeness["privacy"]["binary_payload_scan"]["receipt_set_digest"] = "0" * 64
    rewrite_completeness(completeness)

    with pytest.raises(
        ReleaseInputError,
        match="compiler binary-review receipt differs from its completeness summary",
    ):
        compiler_bundle.load_compiler_bundle(
            compiler_output,
            repository_root=repo,
        )

    current_payload = _one_pixel_png(compression_level=1)
    _write(repo / "docs" / "card.png", current_payload)
    _git(repo, "add", "docs/card.png")
    _git(repo, "commit", "-qm", "changed binary")
    current_commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    current_oid = _git(repo, "rev-parse", f"{current_commit}:docs/card.png").decode("ascii").strip()
    current_record = {
        **record,
        "git_blob_oid": current_oid,
        "raw_sha256": hashlib.sha256(current_payload).hexdigest(),
        "raw_bytes": len(current_payload),
        "automated_format_evidence": inspect_png(current_payload),
    }
    stale_receipt = {
        **receipt,
        "binary_set_digest": binary_set_digest([current_record]),
        "records": [current_record],
    }
    _write(receipt_path, canonical_json(stale_receipt))
    _git(repo, "add", receipt_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-qm", "self-consistent stale basis receipt")

    def hostile_rechain(output: Path, *expected_errors: str) -> None:
        completeness_path = output / "completeness.json"
        manifest_path = output / "manifest.json"
        candidate = json.loads(completeness_path.read_text(encoding="utf-8"))
        scan = candidate["privacy"]["binary_payload_scan"]
        assert scan["status"] == "invalid"
        assert scan["identity_matched_files"] == 0
        assert all(error in scan["error_codes"] for error in expected_errors)

        # Model a hostile compiler-output producer that flips the fail-closed
        # result and rechains the top-level manifest.
        scan["status"] = "incomplete"
        scan["identity_matched_files"] = 1
        scan["review_basis_is_ancestor"] = True
        scan["error_codes"] = ["binary_review_reviewer_authentication_pending"]
        scan["format_aware_or_manual_review_receipt"] = "incomplete"
        candidate_raw = canonical_json(candidate)
        _write(completeness_path, candidate_raw)
        candidate_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate_manifest["completeness"]["sha256"] = sha256_bytes(candidate_raw)
        candidate_manifest["completeness"]["bytes"] = len(candidate_raw)
        _write(manifest_path, canonical_json(candidate_manifest))

    stale_compiler_output = tmp_path / "stale-basis-compiler-output"
    compile_repository(repo, stale_compiler_output)
    hostile_rechain(stale_compiler_output, "binary_review_receipt_identity_mismatch")

    with pytest.raises(
        ReleaseInputError,
        match="compiler binary-review historical basis identity is inconsistent",
    ):
        compiler_bundle.load_compiler_bundle(
            stale_compiler_output,
            repository_root=repo,
        )

    detached_basis = (
        _git(repo, "commit-tree", "HEAD^{tree}", "-m", "detached exact binary basis").decode("ascii").strip()
    )
    detached_receipt = {**stale_receipt, "review_basis_commit": detached_basis}
    _write(receipt_path, canonical_json(detached_receipt))
    _git(repo, "add", receipt_path.relative_to(repo).as_posix())
    _git(repo, "commit", "-qm", "detached non-ancestor basis receipt")
    detached_compiler_output = tmp_path / "detached-basis-compiler-output"
    compile_repository(repo, detached_compiler_output)
    hostile_rechain(
        detached_compiler_output,
        "binary_review_receipt_identity_mismatch",
        "binary_review_receipt_review_basis_not_ancestor",
    )

    with pytest.raises(
        ReleaseInputError,
        match="compiler binary-review historical basis identity is inconsistent",
    ):
        compiler_bundle.load_compiler_bundle(
            detached_compiler_output,
            repository_root=repo,
        )


def test_compiler_bundle_recomputes_declared_claim_census_and_rejects_downgrade_or_json_type_confusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _declared_claim_repository(tmp_path)
    compiler_output = tmp_path / "declared-claim-compiler"
    compile_repository(repo, compiler_output)

    bundle = compiler_bundle.load_compiler_bundle(compiler_output, repository_root=repo)
    summary = bundle.completeness["consequential_claim_denominator"]
    expected_receipts = {
        "master-reference/content/atlas-core.json": (
            155,
            "04ab89206d463fced49716ebef233b71f9e5f5e77e922f7b752dc6cb6c3a4f34",
            "79253dc74d3c25a49179f38b57ea25c7ff603195eb03ee97c5eb38793d78d894",
        ),
        "master-reference/content/capability-catalog.json": (
            422,
            "12c2a143a2955faaf7694f22b78799af833cbd4f8e49a1bed87ea142dfe68917",
            "b92ac8c92f0564c7dd542ffde283633bc8d6e3e5a43aaa77cfef50f65720b18a",
        ),
        "master-reference/content/delivery-governance.json": (
            969,
            "98bdb41437f666511812d40535906835082885e2b51b86f57bc4732865c9b622",
            "623c12f3371523a93aa326169a83ab9eb554a35d2cfcf31668f2618af4774f76",
        ),
        "master-reference/content/open-horizon-register.json": (
            315,
            "e546770f88f1e941de2b2e98582c1aab90a0f0aaf5c581e593b6ef073905656b",
            "0629c2857218a5b6a63a4e6979644ebbbd55753ddba248bde293478f142b35af",
        ),
        "master-reference/content/output-contract.json": (
            275,
            "8a87328023c97c137ca946d01a24d38c2230c22f1b48a51bd3ef1a7d2a49cc6f",
            "3a7fdc2ab75413ec3993a5287edacc97a2fdb7f14f33bd25f47b5575670068d1",
        ),
    }
    assert summary["schema_version"] == "bounded-curated-consequential-claims/2"
    assert summary["state"] == "declared_incomplete"
    assert summary["closed"] is False
    assert summary["source_universe_expected"] == 5
    assert summary["source_universe_registered"] == 5
    assert summary["source_universe_unclassified"] == 0
    assert summary["expected_candidates"] == 2_136
    assert summary["discovered_candidates"] == 2_136
    assert summary["classified_candidates"] == 2_136
    assert summary["independently_reviewed_candidates"] == 0
    assert summary["unresolved_candidates"] == 2_136
    assert summary["candidate_set_digest"] == "a768b5a6c9a94390ada8e9c24627c8908f6a7b51e3f06d59b79ac8f1a5ffdd43"
    assert summary["classification_digest"] == "b5bc4783b8bd6461fc4669b39a555ae061081a278e36712cdb6f70a5e673d1df"
    assert summary["source_receipts_digest"] == "863f93c7bc0599b1cfe7e5b42eb5b10c8087a704af9de194be18d9bf28008689"
    assert summary["error_codes"] == [
        "consequential_claim_independent_review_pending",
        "consequential_claim_rendered_sink_universe_incomplete",
    ]
    assert [receipt["path"] for receipt in summary["source_receipts"]] == list(CONSEQUENTIAL_CLAIM_CONTENT_PATHS)
    for receipt in summary["source_receipts"]:
        count, rule_set_digest, candidate_digest = expected_receipts[receipt["path"]]
        assert set(receipt) == {
            "path",
            "git_blob_oid",
            "sha256",
            "bytes",
            "classification",
            "rule_set_digest",
            "candidate_count",
            "candidate_digest",
        }
        assert receipt["classification"] == "candidate_census"
        assert receipt["candidate_count"] == count
        assert receipt["rule_set_digest"] == rule_set_digest
        assert receipt["candidate_digest"] == candidate_digest

    claim_gate = next(
        item
        for item in bundle.completeness["acceptance_gates"]
        if item["name"] == "consequential_claim_denominator_closed"
    )
    assert claim_gate == {
        "name": "consequential_claim_denominator_closed",
        "passed": False,
        "expected": True,
        "actual": False,
    }

    completeness_path = compiler_output / "completeness.json"
    manifest_path = compiler_output / "manifest.json"
    original_completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def rechain(candidate: dict[str, object]) -> None:
        candidate_raw = canonical_json(candidate)
        _write(completeness_path, candidate_raw)
        manifest = json.loads(json.dumps(original_manifest))
        manifest["completeness"]["sha256"] = sha256_bytes(candidate_raw)
        manifest["completeness"]["bytes"] = len(candidate_raw)
        _write(manifest_path, canonical_json(manifest))

    fixed_error = "compiler consequential-claim census is inconsistent"

    def reject(candidate: dict[str, object], *, repository_root: Path | None = None) -> None:
        rechain(candidate)
        with pytest.raises(ReleaseInputError) as failure:
            compiler_bundle.load_compiler_bundle(
                compiler_output,
                repository_root=repository_root,
            )
        assert str(failure.value) == fixed_error

    downgraded = json.loads(json.dumps(original_completeness))
    downgraded["consequential_claim_denominator"] = unavailable_bounded_curated_claim_summary(
        source_commit=downgraded["source_commit"],
        source_tree_digest=downgraded["source_tree_digest"],
    )
    downgraded["consequential_claim_denominator"]["schema_version"] = "bounded-curated-consequential-claims/1"
    downgraded["semantic_accounting"]["consequential_claim_denominator_state"] = "not_declared"
    for repository_root in (None, repo):
        reject(downgraded, repository_root=repository_root)

    confused = json.loads(json.dumps(original_completeness))
    summary = confused["consequential_claim_denominator"]
    summary["closed"] = 0
    summary["source_universe_registered"] = True
    gate = next(
        item for item in confused["acceptance_gates"] if item["name"] == "consequential_claim_denominator_closed"
    )
    gate["expected"] = 1
    gate["actual"] = 0
    reject(confused, repository_root=repo)

    receipt_mutations = (
        lambda receipts: receipts.pop(),
        lambda receipts: receipts.append(json.loads(json.dumps(receipts[0]))),
        lambda receipts: receipts.__setitem__(slice(0, 2), [receipts[1], receipts[0]]),
    )
    for mutate_receipts in receipt_mutations:
        candidate = json.loads(json.dumps(original_completeness))
        mutate_receipts(candidate["consequential_claim_denominator"]["source_receipts"])
        reject(candidate)

    for field, value in (
        ("candidate_count", 156),
        ("candidate_digest", "0" * 64),
        ("rule_set_digest", "1" * 64),
    ):
        candidate = json.loads(json.dumps(original_completeness))
        candidate["consequential_claim_denominator"]["source_receipts"][0][field] = value
        reject(candidate)

    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\semantic-spec-remap"
    remapped = json.loads(json.dumps(original_completeness))
    remapped["consequential_claim_denominator"]["classification_digest"] = producer_value
    rechain(remapped)
    with pytest.raises(ReleaseInputError) as failure:
        compiler_bundle.load_compiler_bundle(compiler_output)
    assert str(failure.value) == fixed_error
    assert producer_value not in _formatted_exception(failure)

    # Exercise the independent selected-commit comparison after the in-bundle
    # census has recomputed successfully. The injected Git blob never reaches
    # an error surface.
    rechain(original_completeness)
    from release import source_binding

    original_read_git_blobs = source_binding._read_git_blobs
    original_tree_census = source_binding._tree_census

    def mismatched_git_blobs(root: Path, entries: list[object]) -> dict[str, bytes]:
        raw_by_path = original_read_git_blobs(root, entries)
        path = CONSEQUENTIAL_CLAIM_CONTENT_PATHS[0]
        if path in raw_by_path:
            raw_by_path[path] += producer_value.encode("utf-8")
        return raw_by_path

    monkeypatch.setattr(source_binding, "_read_git_blobs", mismatched_git_blobs)
    with pytest.raises(ReleaseInputError) as failure:
        compiler_bundle.load_compiler_bundle(compiler_output, repository_root=repo)
    assert str(failure.value) == fixed_error
    assert producer_value not in _formatted_exception(failure)

    # Exact bytes alone are insufficient: the retained compiler record OID
    # must also be the selected commit's tree OID.  This catches mixed-object-
    # format or substituted object identities before attempting a blob read.
    monkeypatch.setattr(source_binding, "_read_git_blobs", original_read_git_blobs)
    hostile_oid = "f" * 40

    def mismatched_tree_census(root: Path, commit: str) -> list[object]:
        entries = original_tree_census(root, commit)
        target = CONSEQUENTIAL_CLAIM_CONTENT_PATHS[0]
        return [
            type(entry)(
                mode=entry.mode,
                blob_oid=hostile_oid if entry.path == target else entry.blob_oid,
                stage=entry.stage,
                path=entry.path,
            )
            for entry in entries
        ]

    monkeypatch.setattr(source_binding, "_tree_census", mismatched_tree_census)
    with pytest.raises(ReleaseInputError) as failure:
        compiler_bundle.load_compiler_bundle(compiler_output, repository_root=repo)
    assert str(failure.value) == fixed_error
    assert hostile_oid not in _formatted_exception(failure)

    # The emitted subject index is not self-authenticating. Even a fully
    # rechained, schema-valid value digest must match the independently
    # reconstructed selected-commit facet set.
    monkeypatch.setattr(source_binding, "_tree_census", original_tree_census)
    manifest_before_facet_tamper = manifest_path.read_bytes()
    manifest_value = json.loads(manifest_before_facet_tamper)
    facet_relative = manifest_value["groups"]["consequential_claim_facets"]["chunks"][0]["path"]
    facet_path = compiler_output / facet_relative
    facet_before_tamper = facet_path.read_bytes()

    def replace_facet_value_digest(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list) and isinstance(records[0], dict)
        records[0]["value_digest"] = "0" * 64

    _rewrite_chunk(compiler_output, "consequential_claim_facets", replace_facet_value_digest)
    with pytest.raises(ReleaseInputError) as failure:
        compiler_bundle.load_compiler_bundle(compiler_output, repository_root=repo)
    assert str(failure.value) == fixed_error
    _write(facet_path, facet_before_tamper)
    _write(manifest_path, manifest_before_facet_tamper)

    # Subject fingerprints are not evidence. A re-chained compiler claim may
    # not use a facet record to satisfy its evidence relation.
    facet_record_id = json.loads(facet_before_tamper)["records"][0]["id"]
    claims_relative = manifest_value["groups"]["claims"]["chunks"][0]["path"]
    claims_path = compiler_output / claims_relative
    claims_before_tamper = claims_path.read_bytes()

    def replace_claim_evidence_with_facet(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list) and isinstance(records[0], dict)
        records[0]["evidence_ids"] = [facet_record_id]

    _rewrite_chunk(compiler_output, "claims", replace_claim_evidence_with_facet)
    with pytest.raises(ReleaseInputError) as failure:
        compiler_bundle.load_compiler_bundle(compiler_output, repository_root=repo)
    assert str(failure.value) == fixed_error
    _write(claims_path, claims_before_tamper)
    _write(manifest_path, manifest_before_facet_tamper)


def test_dependency_assessment_names_unpatched_image_size_advisories() -> None:
    gate, limits = release_pipeline._dependency_vulnerability_assessment(
        {
            "components": [
                {"name": "image-size", "version": "1.0.0"},
                {"name": "image-size", "version": "2.0.1"},
                {"name": "image-size", "version": "2.0.2"},
                {"name": "image-size", "version": "2.0.3"},
            ]
        }
    )

    assert gate == "blocked_image_size_unpatched_build_time_high_advisories"
    assert len(limits) == 1
    assert "GHSA-5p2g-fcmc-qvqq" in limits[0]
    assert "GHSA-w3rx-r6r6-pgpr" in limits[0]
    assert all(version in limits[0] for version in ("1.0.0", "2.0.1", "2.0.2"))
    assert "2.0.3" not in limits[0]
    assert "not a vulnerability waiver" in limits[0]


def test_release_record_field_registry_matches_tracked_schema_owner() -> None:
    schema = json.loads((MASTER_REFERENCE / "schema" / "atlas-records.schema.json").read_text(encoding="utf-8"))
    schema_registry: dict[str, frozenset[str]] = {}
    for condition in schema["allOf"]:
        group = condition.get("if", {}).get("properties", {}).get("record_type", {}).get("const")
        reference = condition.get("then", {}).get("properties", {}).get("records", {}).get("items", {}).get("$ref")
        if not isinstance(group, str) or not isinstance(reference, str) or not reference.endswith("RecordKeyFence"):
            continue
        definition_name = reference.rsplit("/", maxsplit=1)[-1]
        allowed = schema["$defs"][definition_name]["propertyNames"]["enum"]
        schema_registry[group] = frozenset(allowed)
    assert schema_registry == compiler_bundle._RECORD_KEYS_BY_GROUP


def test_binary_review_bundle_registries_match_completeness_schema_owner() -> None:
    schema = json.loads((MASTER_REFERENCE / "schema" / "completeness-ledger.schema.json").read_text(encoding="utf-8"))
    summary = schema["$defs"]["binaryReviewSummary"]
    error_codes = summary["properties"]["error_codes"]["items"]["enum"]
    custody = schema["$defs"]["pendingReviewerCustody"]

    assert frozenset(summary["required"]) == compiler_bundle._BINARY_SCAN_KEYS
    assert frozenset(error_codes) == compiler_bundle._BINARY_ERROR_CODES
    assert frozenset(error_codes) == binary_review_module._SUMMARY_ERROR_CODES
    assert summary["properties"]["status"]["enum"] == [
        "absent",
        "dirty_preview_not_eligible",
        "invalid",
        "incomplete",
    ]
    assert frozenset(custody["required"]) == frozenset(compiler_bundle._PENDING_REVIEWER_CUSTODY)
    assert custody["properties"]["status"]["const"] == "pending_trusted_external_attestation"
    assert custody["properties"]["required_mechanism"]["const"] == ("detached_signature_with_trusted_public_key")
    for field in (
        "trusted_public_key_configured",
        "detached_signature_present",
        "detached_signature_verified",
        "receipt_claims_trusted",
    ):
        assert custody["properties"][field]["const"] is False
    assert custody["properties"]["authenticated_files"]["const"] == 0
    assert custody["properties"]["authenticated_reviewer_kind"]["type"] == "null"


def test_dependency_assessment_cannot_hide_vulnerable_nanoid_behind_another_finding() -> None:
    gate, limits = release_pipeline._dependency_vulnerability_assessment(
        {
            "components": [
                {"name": "image-size", "version": "2.0.2"},
                {"name": "nanoid", "version": "3.3.16"},
                {"name": "nanoid", "version": "3.3.18"},
            ]
        }
    )

    assert gate == "blocked_multiple_unremediated_high_dependency_advisories"
    assert len(limits) == 2
    assert any("GHSA-2v37-7h3g-55p8" in limit and "3.3.16" in limit for limit in limits)


def test_dependency_assessment_models_nanoid_semver_boundaries_fail_closed() -> None:
    gate, limits = release_pipeline._dependency_vulnerability_assessment(
        {
            "components": [
                {"name": "nanoid", "version": "3.3.16+build.1"},
                {"name": "nanoid", "version": "3.3.17-beta.1"},
                {"name": "nanoid", "version": "3.3.17"},
                {"name": "nanoid", "version": "3.3.18"},
                {"name": "nanoid", "version": "4.0.0"},
                {"name": "nanoid", "version": "5.1.6-beta.1"},
                {"name": "nanoid", "version": "5.1.6"},
                {"name": "nanoid", "version": "unparseable"},
            ]
        }
    )

    assert gate == "blocked_nanoid_unremediated_high_advisory"
    assert len(limits) == 1
    assert "GHSA-2v37-7h3g-55p8" in limits[0]
    for affected in ("3.3.16+build.1", "3.3.17-beta.1", "4.0.0", "5.1.6-beta.1", "unparseable"):
        assert affected in limits[0]
    for patched in ("3.3.17,", "3.3.18", "5.1.6,"):
        assert patched not in limits[0]


def test_dependency_assessment_does_not_flag_patched_nanoid_only() -> None:
    gate, limits = release_pipeline._dependency_vulnerability_assessment(
        {
            "components": [
                {"name": "nanoid", "version": "3.3.17"},
                {"name": "nanoid", "version": "3.3.18"},
                {"name": "nanoid", "version": "5.1.6"},
            ]
        }
    )

    assert gate == "blocked_external_current_advisory_applicability_review_required"
    assert len(limits) == 1
    assert "GHSA-2v37-7h3g-55p8" not in limits[0]


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
    assert any(component.get("purl") == "pkg:npm/devtool@4.0.0" for component in sbom["components"])
    assert any(component.get("purl") == "pkg:npm/dev-leaf@5.0.0" for component in sbom["components"])
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
    component_refs = {component["bom-ref"] for component in sbom["components"]}
    assert len(component_refs) == len(sbom["components"])
    assert len(dependency_map) == len(sbom["dependencies"])
    assert set(dependency_map) == component_refs | {atlas_ref}
    assert {target for targets in dependency_map.values() for target in targets} <= component_refs

    npm_refs = {}
    for component in sbom["components"]:
        properties = {item["name"]: item["value"] for item in component.get("properties", [])}
        lockfile = properties.get("atlas:lockfile")
        lockfile_path = properties.get("atlas:lockfilePath")
        if lockfile and lockfile_path:
            npm_refs[(lockfile, lockfile_path)] = component["bom-ref"]
    for lockfile in ("master-reference/package-lock.json", "webapp/frontend/package-lock.json"):
        root_ref = npm_refs[(lockfile, "<root>")]
        alpha_ref = npm_refs[(lockfile, "node_modules/alpha")]
        gamma_ref = npm_refs[(lockfile, "node_modules/@scope/gamma")]
        devtool_ref = npm_refs[(lockfile, "node_modules/devtool")]
        dev_leaf_ref = npm_refs[(lockfile, "node_modules/dev-leaf")]
        assert {alpha_ref, gamma_ref, devtool_ref} <= dependency_map[root_ref]
        assert dev_leaf_ref in dependency_map[devtool_ref]
        assert root_ref not in dependency_map[devtool_ref]
        devtool = next(component for component in sbom["components"] if component["bom-ref"] == devtool_ref)
        assert {
            item["value"] for item in devtool["properties"] if item["name"] == "atlas:unresolvedOptionalNpmDeclaration"
        } == {"peerDependencies:optional-peer@^6.0.0"}
    assert (
        npm_refs[("master-reference/package-lock.json", "<root>")]
        != npm_refs[("webapp/frontend/package-lock.json", "<root>")]
    )
    assert (
        npm_refs[("master-reference/package-lock.json", "node_modules/alpha")]
        != npm_refs[("webapp/frontend/package-lock.json", "node_modules/alpha")]
    )

    reachable = {atlas_ref}
    pending = [atlas_ref]
    while pending:
        source_ref = pending.pop()
        for target_ref in dependency_map[source_ref]:
            if target_ref not in reachable:
                reachable.add(target_ref)
                pending.append(target_ref)
    assert reachable == component_refs | {atlas_ref}
    denominators = {item["name"]: item["value"] for item in sbom["properties"]}
    assert int(denominators["atlas:componentGraphReachable"]) == len(component_refs)
    assert denominators["atlas:componentGraphDisconnected"] == "0"
    assert denominators["atlas:unresolvedOptionalNpmDeclarations"] == "2"
    assert int(denominators["atlas:dependencyEdges"]) == sum(len(targets) for targets in dependency_map.values())
    python_root = next(
        component["bom-ref"] for component in sbom["components"] if component.get("name") == "fixture-python"
    )
    assert any(ref in dependency_map[python_root] for ref in (component["bom-ref"] for component in python))


def _sbom_source_bytes(repo: Path) -> dict[str, bytes]:
    return {relative: (repo / relative).read_bytes() for relative in (*NPM_LOCKFILES, *PYTHON_DECLARATIONS)}


def test_sbom_rejects_duplicate_component_refs(tmp_path: Path) -> None:
    repo, _ = _fixture_repo(tmp_path)
    sources = _sbom_source_bytes(repo)
    sources["requirements.txt"] += b"alpha-py>=1,<2\n"

    with pytest.raises(ReleaseInputError, match="duplicate component refs"):
        build_cyclonedx(sources, "a" * 40, "b" * 64)


def test_sbom_rejects_disconnected_locked_components(tmp_path: Path) -> None:
    repo, _ = _fixture_repo(tmp_path)
    sources = _sbom_source_bytes(repo)
    lockfile = NPM_LOCKFILES[0]
    lock = json.loads(sources[lockfile].decode("utf-8"))
    lock["packages"]["node_modules/orphan"] = {"version": "9.0.0", "dev": True}
    sources[lockfile] = canonical_json(lock)

    with pytest.raises(ReleaseInputError, match="1 disconnected components"):
        build_cyclonedx(sources, "a" * 40, "b" * 64)


def test_sbom_rejects_unresolved_required_npm_dependencies(tmp_path: Path) -> None:
    repo, _ = _fixture_repo(tmp_path)
    sources = _sbom_source_bytes(repo)
    lockfile = NPM_LOCKFILES[0]
    lock = json.loads(sources[lockfile].decode("utf-8"))
    lock["packages"][""]["dependencies"]["missing-required"] = "1.0.0"
    sources[lockfile] = canonical_json(lock)

    with pytest.raises(ReleaseInputError, match="unresolved npm dependency"):
        build_cyclonedx(sources, "a" * 40, "b" * 64)


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


def test_graph_local_identity_fails_before_family_staging_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    collapsed_repository = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(repo).casefold(),
    ).strip("_")
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={"generated_diagnostic": f"generated_{collapsed_repository}_symbol"},
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert collapsed_repository not in str(failure.value)
    assert not output.exists()


@pytest.mark.parametrize(
    ("producer_value", "rule"),
    [
        (r"D:\Users\Foreign.Person\Desktop\Atlas\graph.json", "generic_windows_user_home_path"),
        ("/home/foreign.person/work/atlas/graph.json", "generic_posix_user_home_path"),
        ("home_foreign_owner_checkout_atlas_graph_json", "generic_collapsed_user_home_path"),
    ],
)
def test_graph_foreign_home_identity_fails_before_family_staging_without_echoing_value(
    tmp_path: Path,
    producer_value: str,
    rule: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={"generated_diagnostic": producer_value},
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_malformed_graph_built_commit_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "producer-controlled build identity"
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={"built_at_commit": producer_value},
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify built commit disposition is absent or inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


@pytest.mark.parametrize("state", ["null", "foreign", "contradictory"])
def test_family_intake_requires_exact_current_graph_built_commit(
    tmp_path: Path,
    state: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    source_commit = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))["source_commit"]
    built_at_commit = {
        "null": None,
        "foreign": "a" * 40,
        "contradictory": source_commit,
    }[state]
    graphify_extra = {
        "built_at_commit": built_at_commit,
        "status": "stale",
        "stale": True,
    }
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra=graphify_extra,
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify built commit disposition is absent or inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    if isinstance(built_at_commit, str) and built_at_commit != source_commit:
        assert built_at_commit not in str(failure.value)
        assert built_at_commit not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_strictly_validates_absent_graph_receipt_before_return(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "producer_private_absent_token"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graphify = {
        "schema_version": "1.2.0",
        "source_commit": manifest["source_commit"],
        "source_tree_digest": manifest["source_tree_digest"],
        "available": False,
        "status": "absent",
        "source": "graphify-out/graph.json",
        "report_available": False,
        "stale": None,
        "unresolved_reasons": ["optional_graphify_projection_not_present"],
        "producer_note": producer_value,
    }
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness["graphify"] = graphify
    graphify_raw = canonical_json(graphify)
    completeness_raw = canonical_json(completeness)
    _write(compiler / "graphify-metadata.json", graphify_raw)
    _write(completeness_path, completeness_raw)
    manifest["graphify_metadata"].update({"sha256": sha256_bytes(graphify_raw), "bytes": len(graphify_raw)})
    manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="Graphify metadata receipt is inconsistent") as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_silent_graph_exclusion_denominator_tamper(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={
            "total_nodes": 2,
            "excluded_nodes": 1,
            "node_disposition_counts": {
                "retained": 1,
                "excluded_unsafe_source": 1,
                "excluded_untracked_or_private": 0,
            },
            "node_identifier_disposition_counts": {
                "total": 2,
                "projected_repository_relative": 1,
                "excluded_opaque": 1,
                "raw_published": 0,
            },
        },
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def _coordinate_only_exclusion_ledger() -> dict[str, object]:
    source_digest = "6" * 64
    excluded_node_id = stable_id("graph-node-disposition", source_digest, 1)
    return {
        "total_nodes": 2,
        "excluded_nodes": 1,
        "excluded_nodes_unsafe_source": 1,
        "node_origins": {"ast": 1, "undisclosed": 1},
        "node_disposition_counts": {
            "retained": 1,
            "excluded_unsafe_source": 1,
            "excluded_untracked_or_private": 0,
        },
        "node_identifier_disposition_counts": {
            "total": 2,
            "projected_repository_relative": 1,
            "excluded_opaque": 1,
            "raw_published": 0,
        },
        "excluded_node_dispositions": [
            {
                "id": excluded_node_id,
                "disposition": "excluded",
                "raw_index": 1,
                "reason": "excluded_unsafe_source",
            }
        ],
        "total_edges": 1,
        "excluded_edges": 1,
        "all_edge_modes": {"undisclosed": 1},
        "projected_edge_modes": {},
        "excluded_edge_dispositions": [
            {
                "id": stable_id("graph-edge-disposition", source_digest, 0),
                "disposition": "excluded",
                "raw_index": 0,
                "reason": "endpoint_not_projected",
                "source_endpoint": {
                    "state": "excluded_unsafe_source",
                    "record_id": excluded_node_id,
                    "anonymous_slot": None,
                },
                "target_endpoint": {
                    "state": "missing_node",
                    "record_id": None,
                    "anonymous_slot": 0,
                },
            }
        ],
        "excluded_edge_endpoint_dispositions": {
            "source_excluded_unsafe_source__target_missing_node": 1,
        },
    }


def test_family_intake_accepts_only_coordinate_ledger_without_raw_hash_commitments(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra=_coordinate_only_exclusion_ledger(),
    )
    output = tmp_path / "release"
    build_release(repo, compiler, output)
    with zipfile.ZipFile(output / "atlas-master-reference-preservation.zip") as archive:
        graphify = json.loads(archive.read("compiler/graphify-metadata.json"))
    forbidden = {
        "opaque_identifier_hash",
        "opaque_record_hash",
        "raw_record_digest",
    }
    node_disposition = graphify["excluded_node_dispositions"][0]
    edge_disposition = graphify["excluded_edge_dispositions"][0]
    assert set(node_disposition) == {"id", "disposition", "raw_index", "reason"}
    assert set(edge_disposition) == {
        "id",
        "disposition",
        "raw_index",
        "reason",
        "source_endpoint",
        "target_endpoint",
    }
    assert forbidden.isdisjoint(node_disposition)
    assert forbidden.isdisjoint(edge_disposition)
    assert forbidden.isdisjoint(edge_disposition["source_endpoint"])
    assert forbidden.isdisjoint(edge_disposition["target_endpoint"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graphify, value: graphify["excluded_node_dispositions"][0].__setitem__("raw_record_digest", value),
        lambda graphify, value: graphify["excluded_edge_dispositions"][0].__setitem__("opaque_record_hash", value),
        lambda graphify, value: graphify["excluded_edge_dispositions"][0]["source_endpoint"].__setitem__(
            "opaque_identifier_hash", value
        ),
    ],
    ids=["node-raw-record", "edge-opaque-record", "endpoint-opaque-identifier"],
)
def test_family_intake_rejects_raw_derived_graph_ledger_fields_without_echo(
    tmp_path: Path,
    mutate: Callable[[dict[str, object], str], None],
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    ledger = _coordinate_only_exclusion_ledger()
    producer_value = "private-dictionary-oracle-sentinel"
    mutate(ledger, producer_value)
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra=ledger,
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graphify: graphify["excluded_edge_dispositions"][0]["target_endpoint"].__setitem__(
            "anonymous_slot", None
        ),
        lambda graphify: graphify["excluded_edge_dispositions"][0]["target_endpoint"].__setitem__("anonymous_slot", 1),
        lambda graphify: graphify["excluded_edge_dispositions"][0].__setitem__(
            "id", stable_id("graph-edge-disposition", "6" * 64, "low-entropy-raw-id")
        ),
    ],
    ids=["missing-anonymous-slot", "noncontiguous-anonymous-slot", "raw-derived-id"],
)
def test_family_intake_rejects_noncanonical_coordinate_ledger_topology(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    ledger = _coordinate_only_exclusion_ledger()
    mutate(ledger)
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra=ledger,
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_reconciles_excluded_edge_retained_endpoint_traversal(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    missing_projected_node = f"urn:atlas:graph-node:{'f' * 24}"
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={
            "total_edges": 1,
            "excluded_edges": 1,
            "all_edge_modes": {"undisclosed": 1},
            "projected_edge_modes": {},
            "excluded_edge_dispositions": [
                {
                    "id": stable_id("graph-edge-disposition", "6" * 64, 0),
                    "disposition": "excluded",
                    "raw_index": 0,
                    "reason": "endpoint_not_projected",
                    "source_endpoint": {
                        "state": "retained",
                        "record_id": missing_projected_node,
                        "anonymous_slot": None,
                    },
                    "target_endpoint": {
                        "state": "missing_node",
                        "record_id": None,
                        "anonymous_slot": 0,
                    },
                }
            ],
            "excluded_edge_endpoint_dispositions": {
                "source_retained__target_missing_node": 1,
            },
        },
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="excluded edge retained endpoint does not traverse to a projected node",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_wraps_malformed_graph_disposition_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas"
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={
            "node_disposition_counts": {
                "retained": 1,
                "excluded_unsafe_source": producer_value,
                "excluded_untracked_or_private": 0,
            },
        },
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_wraps_nonobject_graph_disposition_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas"
    _replace_graph_fixture(
        compiler,
        nodes=[_graph_node(compiler)],
        graphify_extra={
            "total_nodes": 2,
            "excluded_nodes": 1,
            "excluded_node_dispositions": [producer_value],
            "node_disposition_counts": {
                "retained": 1,
                "excluded_unsafe_source": 1,
                "excluded_untracked_or_private": 0,
            },
            "node_identifier_disposition_counts": {
                "total": 2,
                "projected_repository_relative": 1,
                "excluded_opaque": 1,
                "raw_published": 0,
            },
        },
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify exclusion disposition ledger is inconsistent",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_nonobject_graph_record_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_graph_fixture(compiler, nodes=[_graph_node(compiler)])
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_receipt = manifest["groups"]["graph_nodes"]["chunks"][0]
    chunk_path = compiler / chunk_receipt["path"]
    envelope = json.loads(chunk_path.read_text(encoding="utf-8"))
    envelope["records"] = [producer_value]
    chunk_raw = canonical_json(envelope)
    _write(chunk_path, chunk_raw)
    chunk_receipt["sha256"] = sha256_bytes(chunk_raw)
    chunk_receipt["bytes"] = len(chunk_raw)
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler group contains a non-object record: graph_nodes",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_noncanonical_graph_chunk_path_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_graph_fixture(compiler, nodes=[_graph_node(compiler)])
    producer_value = "home_foreign_owner_checkout_graph_nodes"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_receipt = manifest["groups"]["graph_nodes"]["chunks"][0]
    original = compiler / chunk_receipt["path"]
    replacement_relative = f"chunks/graph_nodes/{producer_value}.json"
    replacement = compiler / replacement_relative
    original.replace(replacement)
    chunk_receipt["path"] = replacement_relative
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler chunk owner path is not canonical: group=graph_nodes; index=0",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_noncanonical_graphify_owner_path_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "home_foreign_owner_checkout_graphify"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = compiler / manifest["graphify_metadata"]["path"]
    replacement_relative = f"{producer_value}.json"
    original.replace(compiler / replacement_relative)
    manifest["graphify_metadata"]["path"] = replacement_relative
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler Graphify metadata owner path is not canonical",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_nested_extra_manifest_receipt_fields_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\producer-note"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["files"]["chunks"][0]["producer_note"] = producer_value
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler chunk owner path is not canonical: group=files; index=0",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_extra_chunk_envelope_fields_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\chunk-note"

    def add_extra_field(envelope: dict[str, object]) -> None:
        envelope["producer_note"] = producer_value

    _rewrite_chunk(compiler, "files", add_extra_field)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler chunk envelope mismatch") as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


@pytest.mark.parametrize("group_name", ["files", "graph_nodes", "graph_edges"])
def test_family_intake_rejects_extra_record_fields_in_every_chunk_class_without_echoing_value(
    tmp_path: Path,
    group_name: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    if group_name in {"graph_nodes", "graph_edges"}:
        node = _graph_node(compiler)
        edges = [_graph_edge(compiler, node)] if group_name == "graph_edges" else []
        _replace_graph_fixture(compiler, nodes=[node], edges=edges)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\record-note"

    def add_extra_field(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list) and isinstance(records[0], dict)
        records[0]["producer_note"] = producer_value

    _rewrite_chunk(compiler, group_name, add_extra_field)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match=rf"compiler record contains an undeclared field: group={group_name}; index=0",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_privacy_scans_schema_fallback_record_groups_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\config-note"
    _replace_group_fixture(
        compiler,
        "configs",
        [
            {
                "id": f"urn:atlas:config:{'a' * 24}",
                "producer_note": producer_value,
            }
        ],
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler record contains an undeclared field: group=configs; index=0",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_scans_declared_fields_for_current_host_identity_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = re.sub(r"[^a-z0-9]+", "_", str(repo).casefold()).strip("_")
    _replace_group_fixture(
        compiler,
        "configs",
        [
            {
                "id": f"urn:atlas:config:{'b' * 24}",
                "path": producer_value,
            }
        ],
    )
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match=(
            r"compiler chunk privacy scan failed: "
            r"rule=local_repository_collapsed_path; group=configs; index=0$"
        ),
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_scans_chunk_bytes_for_groups_omitted_from_retention(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = re.sub(r"[^a-z0-9]+", "_", str(repo).casefold()).strip("_")
    _replace_group_fixture(
        compiler,
        "configs",
        [
            {
                "id": f"urn:atlas:config:{'c' * 24}",
                "path": producer_value,
            }
        ],
    )
    retained_groups = set(REQUIRED_GROUPS) - {"configs"}
    with pytest.raises(
        ReleaseInputError,
        match=(
            r"compiler chunk privacy scan failed: "
            r"rule=local_repository_collapsed_path; group=configs; index=0$"
        ),
    ) as failure:
        compiler_bundle.load_compiler_bundle(
            compiler,
            retained_groups=retained_groups,
            repository_root=repo,
        )
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)


def test_family_intake_validates_group_metadata_for_groups_omitted_from_retention(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\group-digest"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["configs"]["records_digest"] = producer_value
    _json(manifest_path, manifest)
    retained_groups = set(REQUIRED_GROUPS) - {"configs"}
    with pytest.raises(ReleaseInputError, match="compiler group is malformed: configs") as failure:
        compiler_bundle.load_compiler_bundle(
            compiler,
            retained_groups=retained_groups,
            repository_root=repo,
        )
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)


def test_generated_identity_scanner_does_not_walk_source_derived_non_graph_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    monkeypatch.setattr(compiler_bundle, "_LOCAL_SCAN_MAX_VALUES", 3)
    compiler_bundle._scan_generated_local_identities(
        {},
        {},
        {},
        {
            "lines": [{"id": "fixture", "payload": "source-derived"}] * 100_000,
            "graph_nodes": [],
            "graph_edges": [],
        },
        repository_root,
    )


def test_family_intake_rejects_container_record_ids_before_digest_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "producer_private_container_id"

    def replace_identifier(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list) and isinstance(records[0], dict)
        records[0]["id"] = [producer_value]
        legacy_digest = digest_object([str(records[0]["id"])])
        envelope["records_digest"] = legacy_digest

    _rewrite_chunk(compiler, "files", replace_identifier)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["files"]["records_digest"] = digest_object([str([producer_value])])
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError) as failure:
        build_release(repo, compiler, output)
    assert "compiler chunk" in str(failure.value)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_noninteger_chunk_size_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\chunk-size"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chunk_size"] = producer_value
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler manifest chunk-size denominator is malformed",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_enforces_single_record_source_text_chunks(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_group_chunk_fixture(
        compiler,
        "source_text",
        [
            [
                {"id": f"urn:atlas:source-text:{'1' * 24}"},
                {"id": f"urn:atlas:source-text:{'2' * 24}"},
            ]
        ],
    )
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler chunk packing is not canonical: source_text"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_rejects_huge_declared_chunk_count_without_allocation(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["groups"]["source_text"] = {
        "record_count": 1_000_000_000_000,
        "chunk_count": 0,
        "records_digest": digest_object([]),
        "chunks": [],
    }
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler chunk packing is not canonical: source_text"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_enforces_canonical_nonfinal_chunk_packing(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    rows = [{"id": f"urn:atlas:config:{index:024x}"} for index in range(2_001)]
    _replace_group_chunk_fixture(compiler, "configs", [rows[:1], rows[1:]])
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler chunk packing is not canonical: configs"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_enforces_strict_ascending_record_order(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    _replace_group_fixture(
        compiler,
        "configs",
        [
            {"id": f"urn:atlas:config:{'2' * 24}"},
            {"id": f"urn:atlas:config:{'1' * 24}"},
        ],
    )
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler record order is not canonical: configs"):
        build_release(repo, compiler, output)
    assert not output.exists()


@pytest.mark.parametrize("owner", ["completeness", "architecture"])
def test_family_intake_scans_self_receipted_generated_owner_metadata_without_echoing_value(
    tmp_path: Path,
    owner: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\producer-note"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    if owner == "completeness":
        completeness["producer_note"] = producer_value
    else:
        architecture_path = compiler / "architecture-conformance.json"
        architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
        architecture["producer_note"] = producer_value
        completeness["architecture_conformance"] = architecture
        architecture_raw = canonical_json(architecture)
        _write(architecture_path, architecture_raw)
        manifest["architecture_conformance"].update(
            {"sha256": sha256_bytes(architecture_raw), "bytes": len(architecture_raw)}
        )
    completeness_raw = canonical_json(completeness)
    _write(completeness_path, completeness_raw)
    manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    expected_path = "completeness"
    with pytest.raises(
        ReleaseError,
        match=rf"local-identity scan failed: rule=generic_windows_user_home_path; path={expected_path}$",
    ) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


@pytest.mark.parametrize(
    ("owner", "expected_error"),
    [
        ("manifest", "unsupported compiler schema"),
        ("completeness", "unsupported compiler completeness schema"),
        ("graphify", "unsupported compiler Graphify schema"),
        ("architecture", "unsupported compiler architecture-conformance schema"),
    ],
)
def test_family_intake_schema_errors_never_echo_producer_values(
    tmp_path: Path,
    owner: str,
    expected_error: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = r"D:\Users\Foreign.Person\Desktop\Atlas\schema"
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if owner == "manifest":
        manifest["schema_version"] = producer_value
    else:
        completeness_path = compiler / "completeness.json"
        completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
        if owner == "completeness":
            completeness["schema_version"] = producer_value
        elif owner == "graphify":
            graphify_path = compiler / "graphify-metadata.json"
            graphify = json.loads(graphify_path.read_text(encoding="utf-8"))
            graphify["schema_version"] = producer_value
            completeness["graphify"] = graphify
            graphify_raw = canonical_json(graphify)
            _write(graphify_path, graphify_raw)
            manifest["graphify_metadata"].update({"sha256": sha256_bytes(graphify_raw), "bytes": len(graphify_raw)})
        else:
            architecture_path = compiler / "architecture-conformance.json"
            architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
            architecture["schema_version"] = producer_value
            completeness["architecture_conformance"] = architecture
            architecture_raw = canonical_json(architecture)
            _write(architecture_path, architecture_raw)
            manifest["architecture_conformance"].update(
                {"sha256": sha256_bytes(architecture_raw), "bytes": len(architecture_raw)}
            )
        completeness_raw = canonical_json(completeness)
        _write(completeness_path, completeness_raw)
        manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match=expected_error) as failure:
        build_release(repo, compiler, output)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_deep_manifest_json_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "home_foreign_owner_checkout_private"
    deep_value = "[" * 2_000 + json.dumps(producer_value) + "]" * 2_000
    (compiler / "manifest.json").write_text(deep_value, encoding="utf-8")
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler manifest shape is not canonical") as failure:
        build_release(repo, compiler, output)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_generated_identity_scanner_rejects_invalid_unicode_without_echoing_value(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    producer_value = "\ud800private"
    with pytest.raises(
        ReleaseInputError,
        match="local-identity scan found an invalid string: path=completeness",
    ) as failure:
        compiler_bundle._scan_generated_local_identities(
            {},
            {"producer_note": producer_value},
            {},
            {"graph_nodes": [], "graph_edges": []},
            repository_root,
        )
    assert producer_value not in _formatted_exception(failure)


def test_family_intake_recomputes_graph_identifier_before_staging(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    node["graphify_id"] = "f" * 64
    node["id"] = stable_id(
        "graph-node",
        json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))["source_commit"],
        node["graphify_id"],
    )
    _replace_graph_fixture(compiler, nodes=[node])
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="unique privacy-safe repository-relative identity",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_rejects_graph_node_anchored_to_privacy_ineligible_file(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    _replace_graph_fixture(compiler, nodes=[node])

    def mark_file_ineligible(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list)
        record = records[0]
        assert isinstance(record, dict)
        record["classification_errors"] = ["fixture_classification_failure"]

    _rewrite_chunk(compiler, "files", mark_file_ineligible)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify node lacks a unique privacy-safe repository-relative identity",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_rejects_graph_edge_anchored_to_privacy_ineligible_file(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    files_receipt = manifest["groups"]["files"]["chunks"][0]
    files_envelope = json.loads((compiler / files_receipt["path"]).read_text(encoding="utf-8"))
    file_records = files_envelope["records"]
    assert isinstance(file_records, list) and len(file_records) >= 2
    second_file = file_records[1]
    assert isinstance(second_file, dict)

    node = _graph_node(compiler)
    edge = _graph_edge(compiler, node)
    edge["source_file"] = second_file["path"]
    edge["source_location"] = "L1"
    edge["id"] = stable_id(
        "graph-edge",
        manifest["source_commit"],
        node["id"],
        node["id"],
        "calls",
        second_file["path"],
        "L1",
        "extracted",
        "none",
        0,
    )
    _replace_graph_fixture(compiler, nodes=[node], edges=[edge])

    def mark_file_ineligible(envelope: dict[str, object]) -> None:
        records = envelope["records"]
        assert isinstance(records, list)
        record = records[1]
        assert isinstance(record, dict)
        record["classification_errors"] = ["fixture_classification_failure"]

    _rewrite_chunk(compiler, "files", mark_file_ineligible)
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="Graphify edge endpoint or stable identity is inconsistent",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


@pytest.mark.parametrize("record_type", ["node", "edge"])
def test_family_intake_rejects_arbitrary_graph_unresolved_reason_without_echoing_value(
    tmp_path: Path,
    record_type: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    producer_value = "producer_private_reason_token"
    node = _graph_node(compiler)
    edges: list[dict[str, object]] = []
    if record_type == "node":
        node["unresolved_reasons"] = [
            *node["unresolved_reasons"],
            producer_value,
        ]
    else:
        edge = _graph_edge(compiler, node)
        edge["unresolved_reasons"] = [producer_value]
        edges = [edge]
    _replace_graph_fixture(compiler, nodes=[node], edges=edges)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError) as failure:
        build_release(repo, compiler, output)
    assert "compiler chunk differs from tracked record schema" in str(failure.value)
    assert producer_value not in str(failure.value)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


@pytest.mark.parametrize("record_type", ["node", "edge"])
def test_family_intake_requires_canonical_graph_unresolved_reason_order(
    tmp_path: Path,
    record_type: str,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    edges: list[dict[str, object]] = []
    if record_type == "node":
        node["origin"] = "curated"
        node["extraction_mode"] = "curated"
        node["unresolved_reasons"] = [
            "graphify_node_origin_is_curated_or_undisclosed_not_ast_extraction",
            "graphify_node_label_derived_from_repository_relative_coordinate",
        ]
    else:
        edge = _graph_edge(compiler, node, extraction_mode="ambiguous")
        edge["relation"] = "related_to"
        edge["unresolved_reasons"] = [
            "graphify_relation_not_in_controlled_vocabulary_shape",
            "graphify_confidence_mode_undisclosed_or_ambiguous",
        ]
        manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
        edge["id"] = stable_id(
            "graph-edge",
            manifest["source_commit"],
            node["id"],
            node["id"],
            "related_to",
            "",
            "",
            "ambiguous",
            "none",
            0,
        )
        edges = [edge]
    _replace_graph_fixture(compiler, nodes=[node], edges=edges)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler Graphify"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_reconciles_projected_community_denominator_from_nodes(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    _replace_graph_fixture(
        compiler,
        nodes=[node],
        graphify_extra={
            "total_communities": 0,
            "projected_communities": 0,
            "all_community_ids": [],
            "projected_community_ids": [],
            "community_status_counts": {
                "projected_complete": 0,
                "projected_partial": 0,
                "excluded": 0,
            },
            "community_dispositions": [],
        },
    )
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="Graphify exclusion disposition ledger is inconsistent"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_reconciles_projected_edge_modes_from_edges(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    edge = _graph_edge(compiler, node)
    _replace_graph_fixture(
        compiler,
        nodes=[node],
        edges=[edge],
        graphify_extra={
            "all_edge_modes": {"inferred": 1},
            "projected_edge_modes": {"inferred": 1},
        },
    )
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="Graphify exclusion disposition ledger is inconsistent"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_rejects_unbounded_graph_source_location_without_echoing_value(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    producer_value = f"L{'9' * 80}"
    node["source_location"] = producer_value
    node["label"] = f"{node['source_file']}:{producer_value}#1"
    node["graphify_id"] = digest_object(["repository-relative-graph-node", node["source_file"], producer_value, "0"])
    manifest = json.loads((compiler / "manifest.json").read_text(encoding="utf-8"))
    node["id"] = stable_id("graph-node", manifest["source_commit"], node["graphify_id"])
    _replace_graph_fixture(compiler, nodes=[node])
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler chunk differs from tracked record schema") as failure:
        build_release(repo, compiler, output)
    assert producer_value not in _formatted_exception(failure)
    assert not output.exists()


def test_family_intake_rejects_arbitrary_graph_producer_text_before_staging(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    node["label"] = "arbitrary producer label"
    _replace_graph_fixture(compiler, nodes=[node])
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="unique privacy-safe repository-relative identity",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_family_intake_rejects_graph_community_outside_js_safe_domain(
    tmp_path: Path,
) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    node = _graph_node(compiler)
    node["community"] = 9_007_199_254_740_992
    _replace_graph_fixture(compiler, nodes=[node])
    output = tmp_path / "release"
    with pytest.raises(
        ReleaseError,
        match="compiler chunk differs from tracked record schema: group=graph_nodes; index=0",
    ):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_architecture_conformance_receipt_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["architecture_conformance"]
    _json(manifest_path, manifest)
    output = tmp_path / "release"
    with pytest.raises(ReleaseError, match="compiler manifest shape is not canonical"):
        build_release(repo, compiler, output)
    assert not output.exists()


def test_missing_structural_line_mapping_gate_blocks_release(tmp_path: Path) -> None:
    repo, compiler = _fixture_repo(tmp_path)
    completeness_path = compiler / "completeness.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness["invariants"] = [
        item for item in completeness["invariants"] if item["name"] != "every_safe_line_structurally_mapped"
    ]
    completeness_raw = canonical_json(completeness)
    completeness_path.write_bytes(completeness_raw)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
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
        if item["name"] != "every_gui_surface_has_standardized_evidence_honest_dossier"
    ]
    completeness_raw = canonical_json(completeness)
    completeness_path.write_bytes(completeness_raw)
    manifest_path = compiler / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
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
    manifest["completeness"].update({"sha256": sha256_bytes(completeness_raw), "bytes": len(completeness_raw)})
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
    assert gate["rendered_sink_lineage"]["state"] == "not_declared"
    assert gate["rendered_sink_lineage"]["closes_global_gate"] is False
    assert gate["rendered_sink_lineage"]["observed_sink_count"] == 0
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
    assert gate["horizon_sink_mechanical_verification"]["verdict"] == "PASS"
    assert gate["horizon_sink_mechanical_verification"]["rendered_observation_count"] == 167
    assert gate["horizon_sink_mechanical_verification"]["safety_observation_count"] == 53
    assert gate["rendered_sink_lineage"]["closes_global_gate"] is False
    assert gate["rendered_sink_lineage"]["state"] == "not_declared"
    assert manifest["release_status"] == "unsigned_preview_incomplete"
    assert manifest["independent_verification_verdict"] == "BLOCK"
    validate_release_object(repo, "pdf-gate", gate)

    for mutate in (
        lambda value: value["rendered_sink_lineage"].update(closes_global_gate=True),
        lambda value: value["rendered_sink_lineage"]["global_denominator"].update(independently_reviewed=315),
        lambda value: value["rendered_sink_lineage"].update(observed_sink_count=1),
        lambda value: value["horizon_sink_mechanical_verification"].update(rendered_observation_count=166),
    ):
        hostile = copy.deepcopy(gate)
        mutate(hostile)
        with pytest.raises(RuntimeError, match="fails pdf-gate schema"):
            validate_release_object(repo, "pdf-gate", hostile)


def test_release_rejects_generated_pdf_replacement_after_mechanical_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    import release.pdf_report as pdf_report

    repo, compiler = _fixture_repo(tmp_path)
    original_build = pdf_report.build_master_reference_pdf

    def build_then_replace(*args, **kwargs):
        result = original_build(*args, **kwargs)
        result.path.write_bytes(b"%PDF-1.4\nhostile replacement\n%%EOF\n")
        return result

    monkeypatch.setattr(pdf_report, "build_master_reference_pdf", build_then_replace)
    with pytest.raises(ReleaseError, match="changed after mechanical verification"):
        build_release(repo, compiler, tmp_path / "release", generate_pdf=True)


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
