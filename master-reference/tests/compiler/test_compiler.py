from __future__ import annotations

import copy
import binascii
import gzip
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from compiler import CompilationError, compile_repository  # noqa: E402
from compiler import binary_review as binary_review_module  # noqa: E402
from compiler import compiler as compiler_module  # noqa: E402
from compiler import graphify as graphify_module  # noqa: E402
from compiler.graphify import GraphifyFailure, project_graphify  # noqa: E402
from compiler.binary_review import (  # noqa: E402
    BinaryReviewFailure,
    binary_set_digest,
    evaluate_tracked_binary_review,
    inspect_gzip_tsv,
    inspect_png,
    parse_tracked_binary_review,
)
from compiler.model import canonical_json, stable_id  # noqa: E402
from compiler.policy import classify_file  # noqa: E402
from compiler.schema_validation import SchemaValidationError, validate_compiler_output  # noqa: E402


def write(root: Path, relative: str, content: str | bytes) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


def git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Atlas Test",
            "GIT_AUTHOR_EMAIL": "atlas@example.invalid",
            "GIT_COMMITTER_NAME": "Atlas Test",
            "GIT_COMMITTER_EMAIL": "atlas@example.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
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
    if process.returncode != 0:
        raise AssertionError(process.stderr)
    return process.stdout.strip()


def git_bytes(root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(process.stderr.decode("utf-8", errors="replace"))
    return process.stdout


def git_blob_oid(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def review_basis_blobs(
    root: Path,
    basis_commit: str,
    paths: tuple[str, ...],
) -> dict[str, tuple[str, bytes]]:
    rows = [row for row in git_bytes(root, "ls-tree", "-r", "--full-tree", "-z", basis_commit).split(b"\0") if row]
    entries: dict[str, str] = {}
    for row in rows:
        metadata, raw_path = row.split(b"\t", 1)
        _mode, object_type, oid = metadata.decode("ascii").split(" ")
        if object_type == "blob":
            entries[raw_path.decode("utf-8", errors="strict")] = oid
    return {
        path: (entries[path], git_bytes(root, "cat-file", "blob", entries[path])) for path in paths if path in entries
    }


def initialize_repository(root: Path, files: dict[str, str | bytes]) -> str:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    for relative, content in files.items():
        write(root, relative, content)
    git(root, "add", "--all")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


def group_records(output: Path, group: str) -> list[dict[str, object]]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    for receipt in manifest["groups"][group]["chunks"]:
        envelope = json.loads((output / receipt["path"]).read_text(encoding="utf-8"))
        records.extend(envelope["records"])
    return records


def output_bytes(output: Path) -> dict[str, bytes]:
    return {
        path.relative_to(output).as_posix(): path.read_bytes() for path in sorted(output.rglob("*")) if path.is_file()
    }


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def one_pixel_png(
    *,
    text_payload: bytes | None = None,
    idat_suffix: bytes = b"",
    compression_level: int = -1,
) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    scanline = b"\x00\x00\x00\x00\xff"
    chunks = [png_chunk(b"IHDR", ihdr)]
    if text_payload is not None:
        chunks.append(png_chunk(b"tEXt", b"Comment\0" + text_payload))
    chunks.extend(
        [
            png_chunk(b"IDAT", zlib.compress(scanline, level=compression_level) + idat_suffix),
            png_chunk(b"IEND", b""),
        ]
    )
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def tracked_binary_receipt(
    root: Path,
    review_basis_commit: str,
    payloads: dict[str, bytes],
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for path, raw in sorted(payloads.items()):
        binary_format = "png" if path.endswith(".png") else "gzip_tsv"
        evidence = inspect_png(raw) if binary_format == "png" else inspect_gzip_tsv(path, raw)
        digest = hashlib.sha256(raw).hexdigest()
        references = (
            [
                f"decoded-rgba-sha256:{hashlib.sha256(bytes((0, 0, 0, 255))).hexdigest()}",
                "privacy-scan:forbidden-local-generic-identities",
                "visual-review:exact-rendered-pixels",
            ]
            if binary_format == "png"
            else [
                f"decoded-tsv-sha256:{evidence['uncompressed_sha256']}",
                "privacy-scan:forbidden-local-generic-identities",
                "registry-validation:retained-source-and-runtime-loader",
            ]
        )
        records.append(
            {
                "path": path,
                "git_blob_oid": git(root, "rev-parse", f"{review_basis_commit}:{path}"),
                "raw_sha256": digest,
                "raw_bytes": len(raw),
                "media_type": "image/png" if binary_format == "png" else "text/tab-separated-values",
                "format": binary_format,
                "automated_format_evidence": evidence,
                "independent_review": {
                    "reviewer_kind": "independent_agent",
                    "reviewer_role": "binary_privacy_verifier",
                    "independent_from_proposer": True,
                    "review_scope": (
                        "rendered_pixels_and_context" if binary_format == "png" else "decoded_tsv_rows_and_context"
                    ),
                    "evidence_references": sorted(references),
                    "verdict": "pass",
                },
            }
        )
    return {
        "schema_version": "tracked-binary-review/1",
        "receipt_kind": "tracked_repository_binary_privacy_review",
        "review_basis_commit": review_basis_commit,
        "binary_set_digest": binary_set_digest(records),
        "records": records,
    }


def commit_binary_receipt(
    root: Path,
    review_basis_commit: str,
    payloads: dict[str, bytes],
    mutate=None,
) -> dict[str, object]:
    receipt = tracked_binary_receipt(root, review_basis_commit, payloads)
    if mutate is not None:
        mutate(receipt)
    write(
        root,
        "master-reference/governance/tracked-binary-review.json",
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    )
    git(root, "add", "master-reference/governance/tracked-binary-review.json")
    git(root, "commit", "-qm", "binary review receipt")
    return receipt


class CompilerTests(unittest.TestCase):
    maxDiff = None

    def test_exact_census_ast_indices_graphify_and_byte_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            commit = initialize_repository(
                repository,
                {
                    "README.md": "# Fixture\n\nStatus: current\n\n[Docs](docs/guide.md)\n",
                    ".claude/agent-memory/MEMORY.md": "# Old working memory\n\nA tracked history hint.\n",
                    ".github/workflows/ci.yml": (
                        "name: CI\n"
                        "on:\n"
                        "  push:\n"
                        "jobs:\n"
                        "  build:\n"
                        "    runs-on: ubuntu-latest\n"
                        "    steps:\n"
                        "      - run: echo ok\n"
                    ),
                    "docs/guide.md": "# Guide\n\nReference text.\n",
                    "notes.txt": "Unstructured but safe.\n",
                    "docs/decisions/0001-proposed.md": "# Decision\n\n**Status:** proposed\n",
                    "reference-data/sample.json": b'\xef\xbb\xbf{"items":[{"name":"one"}],"enabled":true}\r\n',
                    "requirements.txt": "example-package==1.2.3\n",
                    "sample.py": (
                        "# Parser-free comment remains parser-root-owned.\n"
                        "import json\n\n"
                        "def helper(value: str) -> str:\n"
                        "    return json.dumps(value)\n\n"
                        "@app.get('/health')\n"
                        "def health():\n"
                        "    return helper('ok')\n"
                    ),
                    "webapp/src/view.test.tsx": (
                        'import React from "react";\n'
                        'import { Route } from "react-router";\n'
                        "export function Dashboard() {\n"
                        '  return <Route path="/dashboard" element={<div>Ready</div>} />;\n'
                        "}\n"
                        'test("dashboard", () => Dashboard());\n'
                    ),
                },
            )
            graph = {
                "directed": False,
                "multigraph": False,
                "graph": {},
                "built_at_commit": commit,
                "hyperedges": [],
                "nodes": [
                    {
                        "id": "sample_file",
                        "label": "sample.py",
                        "file_type": "code",
                        "source_file": "sample.py",
                        "source_location": "L1",
                        "metadata": {"language": "python", "kind": "file"},
                        "_origin": "ast",
                    },
                    {
                        "id": "sample_helper",
                        "label": "helper",
                        "file_type": "symbol",
                        "source_file": "sample.py",
                        "source_location": "L3",
                        "metadata": {"language": "python", "kind": "function"},
                        "_origin": "ast",
                    },
                ],
                "links": [
                    {
                        "source": "sample_file",
                        "target": "sample_helper",
                        "relation": "contains",
                        "confidence": "INFERRED",
                        "confidence_score": 0.7,
                        "source_file": "sample.py",
                        "source_location": "L3",
                    }
                ],
            }
            write(repository, "graphify-out/graph.json", json.dumps(graph, sort_keys=True))
            write(repository, "graphify-out/GRAPH_REPORT.md", "# Graph report\n")

            first_output = base / "first"
            second_output = base / "second"
            first_manifest = compile_repository(repository, first_output, chunk_size=3)
            second_manifest = compile_repository(repository, second_output, chunk_size=3)

            validate_compiler_output(first_output)

            self.assertEqual(output_bytes(first_output), output_bytes(second_output))
            self.assertEqual(first_manifest["source_commit"], commit)
            self.assertEqual(first_manifest["schema_version"], "1.1.0")
            self.assertEqual(first_manifest["groups"]["files"]["record_count"], 10)
            self.assertEqual(first_manifest["source_tree_digest"], second_manifest["source_tree_digest"])

            files = {record["path"]: record for record in group_records(first_output, "files")}
            self.assertEqual(files[".claude/agent-memory/MEMORY.md"]["privacy_exposure"], "full")
            self.assertEqual(
                files[".claude/agent-memory/MEMORY.md"]["documentation_status"],
                "repository_memory_cache",
            )
            self.assertEqual(
                files["docs/decisions/0001-proposed.md"]["documentation_status"],
                "proposed_decision",
            )
            self.assertEqual(files["webapp/src/view.test.tsx"]["parser"], "typescript_compiler_api")
            self.assertRegex(str(files["webapp/src/view.test.tsx"]["parser_version"]), r"^5\.9\.3$")

            source_records = {record["path"]: record for record in group_records(first_output, "source_text")}
            self.assertEqual(
                set(source_records),
                set(files) - {path for path, row in files.items() if row["privacy_exposure"] != "full"},
            )
            for path, source in source_records.items():
                rebuilt = "".join(str(line["text"]) + str(line["terminator"]) for line in source["lines"]).encode(
                    "utf-8"
                )
                self.assertEqual(len(rebuilt), source["byte_count"])
                self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), source["content_digest"])
                self.assertEqual(source["content_digest"], files[path]["content_digest"])
                self.assertEqual(source["git_blob_oid"], files[path]["git_blob_oid"])
                self.assertEqual(source["source_basis"], "selected_commit_git_blob")
                self.assertEqual(files[path]["content_source"], "selected_commit_git_blob")
            self.assertTrue(str(source_records["reference-data/sample.json"]["lines"][0]["text"]).startswith("\ufeff"))
            self.assertEqual(source_records["reference-data/sample.json"]["lines"][0]["terminator"], "\r\n")
            self.assertEqual(
                first_manifest["groups"]["source_text"]["chunk_count"],
                first_manifest["groups"]["source_text"]["record_count"],
            )

            lines = group_records(first_output, "lines")
            self.assertTrue(lines)
            self.assertTrue(
                {
                    "source_commit",
                    "semantic_entity",
                    "owner",
                    "behavior_group",
                    "inputs_and_outputs",
                    "claims_influenced",
                    "callers_and_dependencies",
                    "tests_covering_it",
                    "runtime_trace_state",
                    "GUI_or_artifact_consumers",
                    "security_and_privacy_effect",
                    "current_or_historical",
                    "explanation_depth",
                    "unresolved_reasons",
                }.issubset(lines[0])
            )
            self.assertTrue(all(int(row["explanation_depth"]) >= 1 for row in lines))
            self.assertEqual(
                next(row for row in lines if row["path"] == "notes.txt")["structural_mapping_basis"],
                "parser_context",
            )
            fallback = next(
                row for row in lines if row["path"] == "sample.py" and row["syntax_kind"] == "unresolved_text"
            )
            structural_roots = {row["path"]: row for row in group_records(first_output, "structural_entities")}
            self.assertEqual(set(structural_roots), set(source_records))
            self.assertEqual(fallback["structural_mapping_basis"], "parser_structural_root")
            self.assertEqual(fallback["semantic_entity"], structural_roots["sample.py"]["id"])
            self.assertNotEqual(fallback["semantic_entity"], files["sample.py"]["id"])
            self.assertEqual(structural_roots["sample.py"]["kind"], "python_module")
            self.assertEqual(
                structural_roots["webapp/src/view.test.tsx"]["kind"],
                "typescript_source_file",
            )
            self.assertTrue(all(row["parser_owned"] for row in structural_roots.values()))
            self.assertTrue(all(row["explanation_depth"] == 1 for row in structural_roots.values()))
            self.assertTrue(
                all(row["generation_provenance"]["state"] == "not_declared" for row in structural_roots.values())
            )
            self.assertIn("behavioral_semantics_not_verified", fallback["unresolved_reasons"])

            self.assertTrue(any(row["qualified_name"] == "helper" for row in group_records(first_output, "symbols")))
            helper = next(row for row in group_records(first_output, "symbols") if row["qualified_name"] == "helper")
            self.assertEqual(helper["stable_urn"], helper["id"])
            self.assertEqual(helper["explanation_depth"], 1)
            self.assertEqual(helper["review_state"], "not_human_reviewed")
            self.assertIn("runtime_trace_not_collected", helper["limitations"])
            self.assertTrue(any(row["name"] == "Dashboard" for row in group_records(first_output, "components")))
            self.assertTrue(any(row["route"] == "/health" for row in group_records(first_output, "routes")))
            self.assertTrue(any(row["route"] == "/dashboard" for row in group_records(first_output, "routes")))
            gui_surfaces = [
                *group_records(first_output, "components"),
                *group_records(first_output, "routes"),
            ]
            self.assertTrue(gui_surfaces)
            self.assertTrue(all("gui_dossier" in row for row in gui_surfaces))
            self.assertTrue(all(row["gui_dossier"]["field_count"] == 15 for row in gui_surfaces))
            self.assertTrue(any(row["name"] == "dashboard" for row in group_records(first_output, "tests")))
            dependency = next(
                row for row in group_records(first_output, "dependencies") if row["name"] == "example-package"
            )
            self.assertEqual(dependency["entity_type"], "dependency")

            claims = group_records(first_output, "claims")
            required_claim_fields = {
                "subject",
                "predicate",
                "value",
                "unit",
                "basis",
                "scope",
                "effective_time",
                "recorded_time",
                "owner",
                "evidence_ids",
                "evidence_class",
                "transformation",
                "denominator",
                "verdict",
                "freshness",
                "lineage",
                "derived_from",
                "status",
                "revoked_by",
                "revocation_reason",
                "conflicts_with",
                "current_view",
                "satisfies_evidence_requirement",
                "source_commit",
                "unresolved_reasons",
            }
            self.assertTrue(claims)
            self.assertTrue(all(required_claim_fields.issubset(row) for row in claims))
            self.assertTrue(all(row["source_commit"] == commit for row in claims))
            commit_time = git(repository, "show", "-s", "--format=%cI", commit)
            self.assertTrue(all(row["effective_time"] == commit_time for row in claims))
            self.assertTrue(all(row["recorded_time"] == row["effective_time"] for row in claims))
            self.assertTrue(all(row["status"] == "current" for row in claims))
            self.assertTrue(all(row["verdict"] == "proven" for row in claims))
            self.assertTrue(all(row["id"] not in row["evidence_ids"] for row in claims))

            workflows = group_records(first_output, "workflows")
            workflow = next(row for row in workflows if row["entity_type"] == "workflow")
            self.assertEqual(workflow["jobs"], ["build"])
            self.assertEqual(workflow["triggers"], ["push"])
            graph_metadata = json.loads((first_output / "graphify-metadata.json").read_text(encoding="utf-8"))
            self.assertFalse(graph_metadata["stale"])
            self.assertEqual(graph_metadata["projected_nodes"], 2)
            self.assertEqual(graph_metadata["projected_edge_modes"], {"inferred": 1})
            self.assertEqual(
                graph_metadata["identifier_projection_policy"],
                "raw_identifiers_withheld_repository_relative_retained_source_index_excluded",
            )
            self.assertEqual(
                graph_metadata["node_identifier_disposition_counts"],
                {
                    "total": 2,
                    "projected_repository_relative": 2,
                    "excluded_opaque": 0,
                    "raw_published": 0,
                },
            )
            graph_nodes = group_records(first_output, "graph_nodes")
            graph_edges = group_records(first_output, "graph_edges")
            self.assertEqual((len(graph_nodes), len(graph_edges)), (2, 1))
            self.assertEqual(len({row["graphify_id"] for row in graph_nodes}), 2)
            self.assertTrue(
                all(
                    len(row["graphify_id"]) == 64 and set(row["graphify_id"]) <= set("0123456789abcdef")
                    for row in graph_nodes
                )
            )
            projected_graph_bytes = (
                b"".join(
                    path.read_bytes()
                    for path in sorted((first_output / "chunks").rglob("*.json"))
                    if path.parent.name in {"graph_nodes", "graph_edges"}
                )
                + (first_output / "graphify-metadata.json").read_bytes()
            )
            self.assertNotIn(b"sample_file", projected_graph_bytes)
            self.assertNotIn(b"sample_helper", projected_graph_bytes)
            self.assertEqual(
                {graph_edges[0]["source"], graph_edges[0]["target"]},
                {row["id"] for row in graph_nodes},
            )
            self.assertIn(
                "graphify_incremental_rebuild_may_evict_cross_file_edges_until_full_rebuild",
                graph_metadata["unresolved_reasons"],
            )

            ledger = json.loads((first_output / "completeness.json").read_text(encoding="utf-8"))
            architecture = json.loads((first_output / "architecture-conformance.json").read_text(encoding="utf-8"))
            manifest = json.loads((first_output / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(ledger["hard_failure"])
            self.assertTrue(all(item["passed"] for item in ledger["invariants"]))
            self.assertEqual(ledger["parsing"]["expected_nonblank_lines"], ledger["parsing"]["line_records"])
            self.assertEqual(
                ledger["semantic_accounting"]["symbol_records"],
                ledger["semantic_accounting"]["symbol_dossiers"],
            )
            self.assertEqual(
                ledger["semantic_accounting"]["gui_surface_records"],
                ledger["semantic_accounting"]["gui_dossiers"],
            )
            self.assertEqual(
                ledger["semantic_accounting"]["structurally_mapped_lines"],
                ledger["parsing"]["line_records"],
            )
            self.assertEqual(
                ledger["semantic_accounting"]["structural_root_entities"],
                ledger["semantic_accounting"]["safe_parsed_sources"],
            )
            self.assertTrue(
                next(
                    item
                    for item in ledger["invariants"]
                    if item["name"] == "every_safe_parsed_source_has_one_structural_root"
                )["passed"]
            )
            self.assertTrue(
                next(item for item in ledger["invariants"] if item["name"] == "every_safe_line_structurally_mapped")[
                    "passed"
                ]
            )
            self.assertTrue(
                next(item for item in ledger["acceptance_gates"] if item["name"] == "exact_clean_commit_binding")[
                    "passed"
                ]
            )
            self.assertEqual(
                ledger["semantic_accounting"]["consequential_claim_denominator_state"],
                "not_declared",
            )
            self.assertEqual(ledger["semantic_accounting"]["bitemporal_event_records"], 0)
            for gate_name in (
                "consequential_claim_denominator_closed",
                "bitemporal_event_ledger_populated_and_replayable",
                "release_lifecycle_transitions_integrated_and_receipted",
            ):
                gate = next(item for item in ledger["acceptance_gates"] if item["name"] == gate_name)
                self.assertFalse(gate["passed"])
                self.assertIs(gate["expected"], True)
                self.assertIs(gate["actual"], False)
            self.assertEqual(architecture, ledger["architecture_conformance"])
            self.assertEqual(architecture["status"], "not_declared")
            self.assertEqual(
                manifest["architecture_conformance"]["sha256"],
                hashlib.sha256((first_output / "architecture-conformance.json").read_bytes()).hexdigest(),
            )

    def test_exact_source_uses_raw_git_blobs_across_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            commit = initialize_repository(
                repository,
                {"portable.py": "def portable():\n    return 'git blob'\n"},
            )
            blob_oid = git(repository, "rev-parse", f"{commit}:portable.py")
            blob = git_bytes(repository, "cat-file", "blob", blob_oid)
            self.assertNotIn(b"\r\n", blob)

            git(repository, "config", "core.autocrlf", "true")
            (repository / "portable.py").unlink()
            git(repository, "checkout", "--", "portable.py")
            self.assertIn(b"\r\n", (repository / "portable.py").read_bytes())
            self.assertEqual(git(repository, "status", "--porcelain=v1"), "")
            crlf_output = base / "crlf"
            compile_repository(repository, crlf_output)

            git(repository, "config", "core.autocrlf", "false")
            (repository / "portable.py").unlink()
            git(repository, "checkout", "--", "portable.py")
            self.assertNotIn(b"\r\n", (repository / "portable.py").read_bytes())
            self.assertEqual(git(repository, "status", "--porcelain=v1"), "")
            lf_output = base / "lf"
            compile_repository(repository, lf_output)

            self.assertEqual(output_bytes(crlf_output), output_bytes(lf_output))
            source = group_records(crlf_output, "source_text")[0]
            file_record = group_records(crlf_output, "files")[0]
            rebuilt = "".join(str(line["text"]) + str(line["terminator"]) for line in source["lines"]).encode("utf-8")
            self.assertEqual(rebuilt, blob)
            self.assertTrue(all(line["terminator"] == "\n" for line in source["lines"]))
            self.assertEqual(source["git_blob_oid"], blob_oid)
            self.assertEqual(source["source_basis"], "selected_commit_git_blob")
            self.assertEqual(file_record["content_source"], "selected_commit_git_blob")
            self.assertEqual(file_record["size_bytes"], len(blob))
            self.assertEqual(file_record["content_digest"], hashlib.sha256(blob).hexdigest())

    def test_absent_graphify_receipt_is_exact_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            commit = initialize_repository(repository, {"README.md": "# No Graphify\n"})
            output = base / "compiled"
            manifest = compile_repository(repository, output)

            metadata = json.loads((output / "graphify-metadata.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["available"])
            self.assertEqual(metadata["status"], "absent")
            self.assertEqual(metadata["schema_version"], "1.1.0")
            self.assertEqual(metadata["source_commit"], commit)
            self.assertEqual(metadata["source_tree_digest"], manifest["source_tree_digest"])
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            gate = next(item for item in ledger["invariants"] if item["name"] == "graphify_receipt_exact_source_bound")
            self.assertTrue(gate["passed"])
            self.assertEqual((gate["expected"], gate["actual"]), (1, 1))

    def test_graphify_projection_accounts_for_excluded_edges_and_communities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {"id": "safe", "source_file": "safe.py", "community": 1, "_origin": "ast"},
                            {"id": "private", "source_file": "private.py", "community": 2, "_origin": "ast"},
                            {"id": "unsafe", "source_file": "../escape.py", "community": 3, "_origin": "ast"},
                            {"id": "mixed-safe", "source_file": "safe.py", "community": 4, "_origin": "ast"},
                            {"id": "mixed-private", "source_file": "private.py", "community": 4, "_origin": "ast"},
                        ],
                        "links": [
                            {"source": "safe", "target": "safe", "relation": "self", "confidence": "extracted"},
                            {"source": "safe", "target": "private", "relation": "hidden"},
                            {"source": "unsafe", "target": "missing", "relation": "opaque"},
                        ],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            metadata, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:safe"},
            )
            self.assertEqual((len(nodes), len(edges)), (2, 1))
            self.assertEqual(
                metadata["node_disposition_counts"],
                {
                    "retained": 2,
                    "excluded_unsafe_source": 1,
                    "excluded_untracked_or_private": 2,
                },
            )
            self.assertEqual(
                metadata["node_identifier_disposition_counts"],
                {
                    "total": 5,
                    "projected_repository_relative": 2,
                    "excluded_opaque": 3,
                    "raw_published": 0,
                },
            )
            self.assertEqual(metadata["excluded_nodes"], 3)
            self.assertEqual(metadata["excluded_edges"], 2)
            self.assertEqual(sum(metadata["excluded_edge_endpoint_dispositions"].values()), 2)
            node_dispositions = metadata["excluded_node_dispositions"]
            edge_dispositions = metadata["excluded_edge_dispositions"]
            self.assertEqual(len(node_dispositions), metadata["excluded_nodes"])
            self.assertEqual(len(edge_dispositions), metadata["excluded_edges"])
            self.assertEqual({item["raw_index"] for item in node_dispositions}, {1, 2, 4})
            self.assertEqual({item["raw_index"] for item in edge_dispositions}, {1, 2})
            self.assertEqual(len({item["id"] for item in node_dispositions}), 3)
            self.assertEqual(len({item["id"] for item in edge_dispositions}), 2)
            self.assertTrue(
                all(
                    item["id"] == stable_id("graph-node-disposition", metadata["source_digest"], item["raw_index"])
                    for item in node_dispositions
                )
            )
            self.assertTrue(
                all(
                    item["id"] == stable_id("graph-edge-disposition", metadata["source_digest"], item["raw_index"])
                    for item in edge_dispositions
                )
            )
            private_disposition = next(item for item in node_dispositions if item["raw_index"] == 1)
            hidden_edge = next(item for item in edge_dispositions if item["raw_index"] == 1)
            self.assertEqual(hidden_edge["target_endpoint"]["record_id"], private_disposition["id"])
            self.assertIsNone(hidden_edge["target_endpoint"]["anonymous_slot"])
            missing_edge = next(item for item in edge_dispositions if item["raw_index"] == 2)
            self.assertEqual(missing_edge["target_endpoint"]["state"], "missing_node")
            self.assertIsNone(missing_edge["target_endpoint"]["record_id"])
            self.assertEqual(missing_edge["target_endpoint"]["anonymous_slot"], 0)
            serialized_dispositions = json.dumps(
                {"nodes": node_dispositions, "edges": edge_dispositions},
                sort_keys=True,
            )
            for forbidden in ("private.py", "../escape.py", "mixed-private", '"hidden"', '"opaque"'):
                self.assertNotIn(forbidden, serialized_dispositions)
            self.assertEqual(metadata["all_community_ids"], [1, 2, 3, 4])
            self.assertEqual(metadata["projected_community_ids"], [1, 4])
            self.assertEqual(metadata["excluded_community_ids"], [2, 3])
            self.assertEqual(metadata["partial_community_ids"], [4])
            self.assertEqual(
                metadata["community_status_counts"],
                {
                    "projected_complete": 1,
                    "projected_partial": 1,
                    "excluded": 2,
                },
            )
            disposition = {item["community"]: item for item in metadata["community_dispositions"]}
            self.assertEqual(disposition[4]["retained_nodes"], 1)
            self.assertEqual(disposition[4]["excluded_nodes"], 1)

    def test_graphify_raw_identifiers_are_withheld_and_public_topology_is_host_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)

            def project(
                raw_ids: tuple[str, str],
                *,
                add_excluded_prefix: bool = False,
            ) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
                nodes = [
                    {
                        "id": raw_ids[0],
                        "label": f"function {raw_ids[0]}",
                        "source_file": "safe.py",
                        "source_location": "L7",
                        "file_type": raw_ids[0],
                        "metadata": {
                            "language": raw_ids[0],
                            "kind": f"symbol_{raw_ids[0]}",
                        },
                        "community": 1,
                        "_origin": raw_ids[0],
                    },
                    {
                        "id": raw_ids[1],
                        "source_file": "safe.py",
                        "source_location": "L7",
                        "community": 1,
                        "_origin": "ast",
                    },
                ]
                links = [
                    {
                        "source": raw_ids[0],
                        "target": raw_ids[1],
                        "relation": f"calls_{raw_ids[0]}",
                        "confidence": "extracted",
                        "source_file": "safe.py",
                        "source_location": "L7",
                    }
                ]
                if add_excluded_prefix:
                    nodes.insert(
                        0,
                        {
                            "id": "private_prefix_node",
                            "source_file": "private.py",
                            "source_location": "L1",
                            "_origin": "ast",
                        },
                    )
                    links.insert(
                        0,
                        {
                            "source": raw_ids[0],
                            "target": "private_prefix_node",
                            "relation": "contains",
                        },
                    )
                write(
                    repository,
                    "graphify-out/graph.json",
                    json.dumps(
                        {
                            "built_at_commit": "a" * 40,
                            "nodes": nodes,
                            "links": links,
                            "hyperedges": [],
                        },
                        sort_keys=True,
                    ),
                )
                return project_graphify(
                    repository,
                    "a" * 40,
                    "b" * 64,
                    {"safe.py": "urn:atlas:file:" + "c" * 24},
                )

            windows_and_posix_derived = (
                "c_users_owner_desktop_checkout_safe",
                "home_owner_checkout_safe",
            )
            different_host_derived = (
                "d_build_agents_second_checkout_safe",
                "srv_ci_second_checkout_safe",
            )
            first_metadata, first_nodes, first_edges = project(windows_and_posix_derived)
            second_metadata, second_nodes, second_edges = project(different_host_derived)
            prefixed_metadata, prefixed_nodes, prefixed_edges = project(
                different_host_derived,
                add_excluded_prefix=True,
            )

            self.assertEqual((len(first_nodes), len(first_edges)), (2, 1))
            self.assertEqual(first_nodes, second_nodes)
            self.assertEqual(first_edges, second_edges)
            self.assertEqual(first_nodes, prefixed_nodes)
            self.assertEqual(first_edges, prefixed_edges)
            self.assertEqual(prefixed_metadata["excluded_nodes"], 1)
            self.assertEqual(prefixed_metadata["excluded_edges"], 1)
            self.assertEqual(
                {row["label"] for row in first_nodes},
                {"safe.py:L7#1", "safe.py:L7#2"},
            )
            producer_text_adversary = next(row for row in first_nodes if row["coordinate_occurrence"] == 0)
            self.assertEqual(producer_text_adversary["origin"], "undisclosed")
            self.assertEqual(producer_text_adversary["file_type"], "")
            self.assertEqual(producer_text_adversary["language"], "")
            self.assertEqual(producer_text_adversary["kind"], "")
            self.assertEqual(first_edges[0]["relation"], "related_to")
            self.assertIn(
                "graphify_relation_not_in_controlled_vocabulary_shape",
                first_edges[0]["unresolved_reasons"],
            )
            self.assertEqual(
                first_metadata["node_identifier_disposition_counts"],
                {
                    "total": 2,
                    "projected_repository_relative": 2,
                    "excluded_opaque": 0,
                    "raw_published": 0,
                },
            )
            node_ids = {row["id"] for row in first_nodes}
            self.assertEqual(
                {first_edges[0]["source"], first_edges[0]["target"]},
                node_ids,
            )
            self.assertEqual(len({row["graphify_id"] for row in first_nodes}), 2)
            outward = json.dumps(
                {"metadata": first_metadata, "nodes": first_nodes, "edges": first_edges},
                sort_keys=True,
            )
            for raw_id in windows_and_posix_derived:
                self.assertNotIn(raw_id, outward)
            second_outward = json.dumps(
                {"metadata": second_metadata, "nodes": second_nodes, "edges": second_edges},
                sort_keys=True,
            )
            for raw_id in different_host_derived:
                self.assertNotIn(raw_id, second_outward)

    def test_graphify_exclusion_dispositions_are_coordinate_only_with_anonymous_missing_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)

            def project(
                excluded_id: str,
                first_missing_id: str,
                second_missing_id: str,
                private_payload: str,
            ) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
                excluded_node = {
                    "id": excluded_id,
                    "source_file": "private.py",
                    "producer_note": private_payload,
                    "_origin": "ast",
                }
                payload = {
                    "built_at_commit": "a" * 40,
                    "nodes": [
                        {"id": "safe", "source_file": "safe.py", "source_location": "L1", "_origin": "ast"},
                        excluded_node,
                    ],
                    "links": [
                        {"source": "safe", "target": excluded_id},
                        {"source": "safe", "target": first_missing_id},
                        {"source": first_missing_id, "target": "safe"},
                        {"source": "safe", "target": second_missing_id},
                        {"source": first_missing_id, "target": second_missing_id},
                    ],
                    "hyperedges": [],
                }
                write(repository, "graphify-out/graph.json", json.dumps(payload, sort_keys=True))
                metadata, nodes, edges = project_graphify(
                    repository,
                    "a" * 40,
                    "b" * 64,
                    {"safe.py": "urn:atlas:file:" + "c" * 24},
                )
                return metadata, nodes, edges, excluded_node

            first = project("alice", "missing_a", "missing_b", "low-entropy-private-payload")
            second = project("bob", "unknown_x", "unknown_y", "different-private-payload")
            first_metadata, first_nodes, first_edges, first_raw_node = first
            second_metadata, second_nodes, second_edges, _ = second
            self.assertEqual((len(first_nodes), len(first_edges)), (1, 0))
            self.assertEqual((len(second_nodes), len(second_edges)), (1, 0))
            self.assertNotEqual(first_metadata["source_digest"], second_metadata["source_digest"])

            def normalized_dispositions(metadata: dict[str, object]) -> dict[str, object]:
                value = {
                    "nodes": copy.deepcopy(metadata["excluded_node_dispositions"]),
                    "edges": copy.deepcopy(metadata["excluded_edge_dispositions"]),
                }
                for record in value["nodes"]:
                    record["id"] = f"node-source-index-{record['raw_index']}"
                for record in value["edges"]:
                    record["id"] = f"edge-source-index-{record['raw_index']}"
                    for endpoint_name in ("source_endpoint", "target_endpoint"):
                        endpoint = record[endpoint_name]
                        if endpoint["record_id"] is not None:
                            endpoint["record_id"] = endpoint["state"]
                value["nodes"].sort(key=lambda record: record["raw_index"])
                value["edges"].sort(key=lambda record: record["raw_index"])
                return value

            self.assertEqual(
                normalized_dispositions(first_metadata),
                normalized_dispositions(second_metadata),
            )
            node_disposition = first_metadata["excluded_node_dispositions"][0]
            self.assertEqual(set(node_disposition), {"id", "disposition", "raw_index", "reason"})
            self.assertEqual(
                node_disposition["id"],
                stable_id("graph-node-disposition", first_metadata["source_digest"], 1),
            )
            edge_dispositions = {record["raw_index"]: record for record in first_metadata["excluded_edge_dispositions"]}
            self.assertEqual(edge_dispositions[1]["target_endpoint"]["anonymous_slot"], 0)
            self.assertEqual(edge_dispositions[2]["source_endpoint"]["anonymous_slot"], 0)
            self.assertEqual(edge_dispositions[3]["target_endpoint"]["anonymous_slot"], 1)
            self.assertEqual(edge_dispositions[4]["source_endpoint"]["anonymous_slot"], 0)
            self.assertEqual(edge_dispositions[4]["target_endpoint"]["anonymous_slot"], 1)
            self.assertIsNone(edge_dispositions[0]["target_endpoint"]["anonymous_slot"])

            source_digest = first_metadata["source_digest"]
            raw_record_digest = hashlib.sha256(canonical_json(first_raw_node)).hexdigest()
            legacy_identifier_commitment = hashlib.sha256(
                canonical_json([source_digest, "node-identifier", "alice"])
            ).hexdigest()
            legacy_record_commitment = hashlib.sha256(
                canonical_json([source_digest, "excluded-node-record", "1", raw_record_digest])
            ).hexdigest()
            outward = json.dumps(
                {
                    "metadata": first_metadata,
                    "nodes": first_nodes,
                    "edges": first_edges,
                },
                sort_keys=True,
            )
            for forbidden in (
                "alice",
                "missing_a",
                "missing_b",
                "low-entropy-private-payload",
                raw_record_digest,
                legacy_identifier_commitment,
                legacy_record_commitment,
                "raw_record_digest",
                "opaque_identifier_hash",
                "opaque_record_hash",
            ):
                self.assertNotIn(forbidden, outward)

    def test_graphify_repository_relative_identifier_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {"id": "one", "source_file": "safe.py", "source_location": "L1", "_origin": "ast"},
                            {"id": "two", "source_file": "safe.py", "source_location": "L2", "_origin": "ast"},
                        ],
                        "links": [],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            with mock.patch.object(
                graphify_module,
                "_projected_identifier_hash",
                return_value="a" * 64,
            ):
                with self.assertRaisesRegex(
                    GraphifyFailure,
                    "repository-relative node identifiers are not one-to-one",
                ):
                    project_graphify(
                        repository,
                        "a" * 40,
                        "b" * 64,
                        {"safe.py": "urn:atlas:file:" + "c" * 24},
                    )

    def test_graphify_malformed_built_commit_is_withheld_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            local_marker = "c_users_foreign_owner_desktop_checkout"
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": local_marker,
                        "nodes": [
                            {
                                "id": "safe_node",
                                "source_file": "safe.py",
                                "source_location": "L1",
                                "_origin": "ast",
                            }
                        ],
                        "links": [],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            metadata, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:" + "c" * 24},
            )
            self.assertEqual((len(nodes), len(edges)), (1, 0))
            self.assertIsNone(metadata["built_at_commit"])
            self.assertIn(
                "graphify_built_at_commit_missing_or_malformed_and_withheld",
                metadata["unresolved_reasons"],
            )
            self.assertNotIn(
                local_marker,
                json.dumps(metadata, sort_keys=True),
            )
            current_without_matching_commit = dict(metadata)
            current_without_matching_commit.update({"status": "current", "stale": False})
            with self.assertRaisesRegex(
                GraphifyFailure,
                "built commit and source freshness are inconsistent",
            ):
                graphify_module.validate_graphify_metadata(current_without_matching_commit)
            stale_with_matching_commit = dict(metadata)
            stale_with_matching_commit.update({"built_at_commit": "a" * 40, "status": "stale", "stale": True})
            with self.assertRaisesRegex(
                GraphifyFailure,
                "unresolved reason ledger is malformed",
            ):
                graphify_module.validate_graphify_metadata(stale_with_matching_commit)
            current_with_dirty_reason = dict(metadata)
            current_with_dirty_reason.update(
                {
                    "built_at_commit": "a" * 40,
                    "status": "current",
                    "stale": False,
                    "unresolved_reasons": [
                        *metadata["unresolved_reasons"],
                        "tracked_worktree_changes_are_newer_than_commit_bound_graph",
                    ],
                }
            )
            with self.assertRaisesRegex(
                GraphifyFailure,
                "unresolved reason ledger is malformed",
            ):
                graphify_module.validate_graphify_metadata(current_with_dirty_reason)
            contradictory = dict(metadata)
            contradictory.update({"status": "current", "stale": True})
            with self.assertRaisesRegex(
                GraphifyFailure,
                "status and freshness disposition are inconsistent",
            ):
                graphify_module.validate_graphify_metadata(contradictory)

    def test_graphify_community_is_bounded_to_js_safe_nonnegative_integers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {
                                "id": f"node_{index}",
                                "source_file": "safe.py",
                                "source_location": f"L{index + 1}",
                                "community": community,
                                "_origin": "ast",
                            }
                            for index, community in enumerate((9_007_199_254_740_991, 9_007_199_254_740_992, -1, True))
                        ],
                        "links": [],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            metadata, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:" + "c" * 24},
            )
            self.assertEqual((len(nodes), len(edges)), (4, 0))
            self.assertEqual(metadata["all_community_ids"], [9_007_199_254_740_991])
            self.assertEqual(
                sorted(row["community"] for row in nodes if row["community"] is not None),
                [9_007_199_254_740_991],
            )
            withheld = [row for row in nodes if row["community"] is None]
            self.assertEqual(len(withheld), 3)
            self.assertTrue(
                all(
                    "graphify_node_community_outside_js_safe_nonnegative_integer_domain" in row["unresolved_reasons"]
                    for row in withheld
                )
            )

    def test_graphify_identical_coordinate_reordering_preserves_public_multisets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)

            def project(
                *,
                reverse_nodes: bool = False,
                reverse_edges: bool = False,
                include_edges: bool = True,
                add_excluded_vocabulary_ids: bool = False,
            ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
                nodes = [
                    {
                        "id": raw_id,
                        "label": raw_id,
                        "file_type": "code",
                        "source_file": "safe.py",
                        "source_location": "L9",
                        "_origin": "ast",
                    }
                    for raw_id in ("duplicate_alpha", "duplicate_beta")
                ]
                if reverse_nodes:
                    nodes.reverse()
                if add_excluded_vocabulary_ids:
                    nodes[:0] = [
                        {
                            "id": raw_id,
                            "source_file": f"private-{raw_id}.py",
                            "_origin": "ast",
                        }
                        for raw_id in ("calls", "python", "function", "code")
                    ]
                edges = (
                    [
                        {
                            "source": "duplicate_alpha",
                            "target": "duplicate_beta",
                            "relation": "calls",
                            "confidence": "extracted",
                            "confidence_score": 0.5,
                            "source_file": "safe.py",
                            "source_location": "L9",
                            "producer_note": producer_note,
                        }
                        for producer_note in ("first", "second")
                    ]
                    if include_edges
                    else []
                )
                if reverse_edges:
                    edges.reverse()
                write(
                    repository,
                    "graphify-out/graph.json",
                    json.dumps(
                        {
                            "built_at_commit": "a" * 40,
                            "nodes": nodes,
                            "links": edges,
                            "hyperedges": [],
                        },
                        sort_keys=True,
                    ),
                )
                _, projected_nodes, projected_edges = project_graphify(
                    repository,
                    "a" * 40,
                    "b" * 64,
                    {"safe.py": "urn:atlas:file:" + "c" * 24},
                )
                return projected_nodes, projected_edges

            nodes_forward, _ = project(include_edges=False)
            nodes_reversed, _ = project(reverse_nodes=True, include_edges=False)
            self.assertEqual(nodes_forward, nodes_reversed)

            nodes_with_edges, edges_forward = project()
            nodes_with_reversed_edges, edges_reversed = project(reverse_edges=True)
            nodes_with_excluded_ids, edges_with_excluded_ids = project(add_excluded_vocabulary_ids=True)
            self.assertEqual(nodes_with_edges, nodes_with_reversed_edges)
            self.assertEqual(edges_forward, edges_reversed)
            self.assertEqual(nodes_with_edges, nodes_with_excluded_ids)
            self.assertEqual(edges_forward, edges_with_excluded_ids)
            self.assertEqual(
                {row["coordinate_occurrence"] for row in edges_forward},
                {0, 1},
            )

    def test_graphify_controlled_vocabulary_projection_handles_large_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            node_count = 128
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {
                                "id": f"producer_node_{index:04d}",
                                "label": f"producer_node_{index:04d}",
                                "file_type": "code",
                                "source_file": "safe.py",
                                "source_location": "L1",
                                "_origin": "ast",
                            }
                            for index in range(node_count)
                        ],
                        "links": [
                            {
                                "source": "producer_node_0000",
                                "target": f"producer_node_{index:04d}",
                                "relation": "calls",
                                "confidence": "extracted",
                                "confidence_score": 1,
                                "source_file": "safe.py",
                                "source_location": "L1",
                            }
                            for index in range(1, node_count)
                        ],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            _, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:" + "c" * 24},
            )
            self.assertEqual((len(nodes), len(edges)), (node_count, node_count - 1))

    def test_graphify_exclusion_disposition_uniqueness_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {"id": "private-a", "source_file": "private-a.py", "_origin": "ast"},
                            {"id": "private-b", "source_file": "private-b.py", "_origin": "ast"},
                        ],
                        "links": [],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            duplicate = {
                "id": "urn:atlas:graph-node-disposition:" + "a" * 24,
                "disposition": "excluded",
                "raw_index": 0,
                "reason": "excluded_untracked_or_private",
            }
            with mock.patch.object(
                graphify_module,
                "_excluded_node_record",
                return_value=duplicate,
            ):
                with self.assertRaisesRegex(
                    GraphifyFailure,
                    "exclusion disposition reconciliation failed",
                ):
                    project_graphify(repository, "a" * 40, "b" * 64, {})

    def test_mismatched_graphify_source_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"README.md": "# Graphify mismatch\n"})
            output = base / "failed"
            mismatched = {
                "schema_version": "1.1.0",
                "source_commit": "0" * 40,
                "source_tree_digest": "1" * 64,
                "available": False,
                "status": "absent",
                "stale": None,
                "unresolved_reasons": ["synthetic_mismatched_binding"],
            }
            with mock.patch.object(
                compiler_module,
                "project_graphify",
                return_value=(mismatched, [], []),
            ):
                with self.assertRaises(CompilationError):
                    compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["hard_failure"])
            self.assertTrue(ledger["fatal_errors"])
            self.assertFalse((output / "manifest.json").exists())

    def test_closed_entity_denominator_extracts_declared_entities_without_invented_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(
                repository,
                {
                    "entities.py": (
                        "import argparse\n"
                        "MAX_RETRIES = 3\n"
                        "runtime_registry = {}\n\n"
                        "class Settings:\n"
                        "    TIMEOUT = 30\n"
                        "    label = 'candidate binding'\n\n"
                        "parser = argparse.ArgumentParser(prog='atlas')\n"
                        "subcommands = parser.add_subparsers()\n"
                        "deploy = subcommands.add_parser('deploy')\n"
                    ),
                    "tests/test_entities.py": (
                        "import pytest\n\n"
                        "def test_truth():\n"
                        "    assert 1 + 1 == 2\n"
                        "    with pytest.raises(ValueError):\n"
                        "        raise ValueError('expected')\n"
                    ),
                    "webapp/src/entities.test.tsx": (
                        "const LIMIT = 3;\n"
                        "const { alpha, beta } = { alpha: 1, beta: 2 };\n"
                        "export const Widget = () => <section><span /></section>;\n"
                        "test('limit', () => expect(LIMIT).toBe(3));\n"
                        "it.each([[1]])('row %s', (value) => expect(value).toBe(1));\n"
                    ),
                    "webapp/src/entities.css": (
                        ":root { --space: 4px; }\n"
                        ".card, [data-state='open'] { color: red; }\n"
                        "@media (min-width: 40rem) { .card { display: grid; } }\n"
                    ),
                    "webapp/src/index.html": (
                        "<!doctype html><main><template id='row'></template><x-card></x-card></main>\n"
                    ),
                    "webapp/src/icon.svg": "<svg viewBox='0 0 1 1'><path d='M0 0'/></svg>\n",
                    "tools/run.sh": "#!/bin/sh\nMODE=test\nnpm test\n",
                    "tools/run.ps1": "$Mode = 'test'\n& npm test\n",
                    "master-reference/sample.jsonc": '{\n  // structural only\n  "theme": "dark"\n}\n',
                    "pyproject.toml": (
                        "[project]\n"
                        "name = 'fixture'\n"
                        "version = '1.0.0'\n\n"
                        "[project.scripts]\n"
                        "fixture-cli = 'entities:main'\n"
                    ),
                    "reference-data/table.csv": 'name,value\none,1\n"two\nlines",2\n',
                    ".github/workflows/ci.yml": (
                        "name: CI\n"
                        "on: [push]\n"
                        "permissions:\n"
                        "  contents: read\n"
                        "jobs:\n"
                        "  build:\n"
                        "    runs-on: ubuntu-latest\n"
                        "    permissions:\n"
                        "      checks: write\n"
                        "    steps:\n"
                        "      - name: Checkout\n"
                        "        uses: actions/checkout@v4\n"
                        "      - name: Bundle\n"
                        "        run: npm run build\n"
                        "      - name: Preserve bundle\n"
                        "        uses: actions/upload-artifact@v4\n"
                        "        with:\n"
                        "          name: atlas-bundle\n"
                        "          path: dist/\n"
                    ),
                },
            )
            output = base / "compiled"
            compile_repository(repository, output)

            symbols = group_records(output, "symbols")
            symbol_types = {(row["name"], row["entity_type"]) for row in symbols}
            self.assertIn(("MAX_RETRIES", "python_module_constant"), symbol_types)
            self.assertIn(("TIMEOUT", "python_class_constant"), symbol_types)
            self.assertIn(("atlas", "python_cli_command"), symbol_types)
            self.assertIn(("deploy", "python_cli_subcommand"), symbol_types)
            self.assertIn(("fixture-cli", "declared_cli_command"), symbol_types)
            self.assertTrue(
                {"LIMIT", "alpha", "beta", "Widget"}.issubset(
                    {row["name"] for row in symbols if row["entity_type"] == "typescript_constant"}
                )
            )
            css_selectors = [row for row in symbols if row["entity_type"] == "css_selector"]
            self.assertEqual(
                {row["name"] for row in css_selectors},
                {":root", ".card", "[data-state='open']"},
            )
            self.assertTrue(all(int(row["explanation_depth"]) <= 1 for row in symbols))

            components = group_records(output, "components")
            component_types = [row["entity_type"] for row in components]
            self.assertIn("html_element", component_types)
            self.assertIn("svg_element", component_types)
            self.assertIn("jsx_element", component_types)

            calls = group_records(output, "calls")
            self.assertTrue(any(row["entity_type"] == "shell_command_candidate" for row in calls))
            self.assertTrue(any(row["entity_type"] == "powershell_command_candidate" for row in calls))

            structured = group_records(output, "structured")
            self.assertTrue(any(row["entity_type"] == "configuration_key" for row in structured))
            self.assertEqual(sum(row["entity_type"] == "csv_header_row" for row in structured), 1)
            self.assertEqual(sum(row["entity_type"] == "csv_data_row" for row in structured), 2)
            dataset = next(row for row in structured if row["entity_type"] == "csv_dataset")
            self.assertEqual(dataset["row_count_including_header"], 3)
            self.assertEqual(dataset["row_accounting_state"], "complete")

            workflows = group_records(output, "workflows")
            self.assertEqual(sum(row["entity_type"] == "workflow_job" for row in workflows), 1)
            self.assertEqual(sum(row["entity_type"] == "workflow_step" for row in workflows), 3)
            self.assertEqual(sum(row["entity_type"] == "workflow_permission" for row in workflows), 2)
            self.assertEqual(sum(row["entity_type"] == "workflow_artifact" for row in workflows), 1)

            tests = group_records(output, "tests")
            assertion_groups = [row for row in tests if row["entity_type"] == "test_assertion_group"]
            self.assertEqual(len(assertion_groups), 3)
            self.assertTrue(all(int(row["assertion_count"]) >= 1 for row in assertion_groups))
            self.assertFalse(any(row["name"] == "it.each" for row in tests))

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["record_counts"]["entity_type::csv_data_row"], 2)
            self.assertEqual(ledger["record_counts"]["entity_type::workflow_step"], 3)
            typed_gate = next(
                item for item in ledger["invariants"] if item["name"] == "every_published_record_has_entity_type"
            )
            self.assertTrue(typed_gate["passed"])

    def test_python_symbol_identity_is_stable_while_source_digest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"sample.py": "def transform(value):\n    return value + 1\n"})
            first_output = base / "first"
            compile_repository(repository, first_output)
            first = next(row for row in group_records(first_output, "symbols") if row["name"] == "transform")

            write(repository, "sample.py", "def transform(value):\n    return value + 2\n")
            git(repository, "add", "sample.py")
            git(repository, "commit", "-qm", "change body")
            second_output = base / "second"
            compile_repository(repository, second_output)
            second = next(row for row in group_records(second_output, "symbols") if row["name"] == "transform")

            self.assertEqual(first["id"], second["id"])
            self.assertNotEqual(first["digest"], second["digest"])

    def test_dirty_tracked_worktree_requires_explicit_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"README.md": "# Clean\n"})
            write(repository, "README.md", "# Dirty\n")

            blocked = base / "blocked"
            with self.assertRaises(CompilationError) as caught:
                compile_repository(repository, blocked)
            self.assertIn("exact-commit compilation requires a clean tracked tree", " ".join(caught.exception.errors))
            self.assertFalse((blocked / "manifest.json").exists())

            preview = base / "preview"
            manifest = compile_repository(repository, preview, allow_dirty_preview=True)
            self.assertEqual(manifest["release_class"], "dirty_preview")
            ledger = json.loads((preview / "completeness.json").read_text(encoding="utf-8"))
            self.assertFalse(
                next(item for item in ledger["acceptance_gates"] if item["name"] == "exact_clean_commit_binding")[
                    "passed"
                ]
            )

            claims = group_records(preview, "claims")
            self.assertTrue(
                all(row["content_source"] == "dirty_preview_worktree" for row in group_records(preview, "files"))
            )
            self.assertTrue(
                all(row["source_basis"] == "dirty_preview_worktree" for row in group_records(preview, "source_text"))
            )
            self.assertTrue(all(row["status"] == "candidate" for row in claims))
            self.assertTrue(all(row["verdict"] == "indeterminate" for row in claims))
            self.assertTrue(all(row["freshness"] == "unknown" for row in claims))
            self.assertTrue(all(not row["current_view"] for row in claims))
            self.assertTrue(all("dirty_worktree_not_exact_commit_bound" in row["unresolved_reasons"] for row in claims))

    def test_structural_line_gate_fails_closed_if_enrichment_drops_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"notes.txt": "A safe source line.\n"})
            output = base / "failed"
            original = compiler_module._enrich_semantic_records

            def remove_mapping(*args: object, **kwargs: object) -> None:
                original(*args, **kwargs)
                records = args[0]
                assert isinstance(records, dict)
                records["lines"][0]["explanation_depth"] = 0
                records["lines"][0].pop("structural_mapping_basis")

            with mock.patch.object(
                compiler_module,
                "_enrich_semantic_records",
                side_effect=remove_mapping,
            ):
                with self.assertRaises(CompilationError):
                    compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            gate = next(item for item in ledger["invariants"] if item["name"] == "every_safe_line_structurally_mapped")
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["expected"], 1)
            self.assertEqual(gate["actual"], 0)
            self.assertTrue(ledger["hard_failure"])
            self.assertFalse((output / "manifest.json").exists())

    def test_structural_line_gate_rejects_file_record_as_semantic_entity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"notes.txt": "A safe source line.\n"})
            output = base / "failed"
            original = compiler_module._enrich_semantic_records

            def orphan_mapping(*args: object, **kwargs: object) -> None:
                original(*args, **kwargs)
                records = args[0]
                file_records = args[1]
                assert isinstance(records, dict)
                assert isinstance(file_records, list)
                records["lines"][0]["semantic_entity"] = file_records[0]["id"]

            with mock.patch.object(
                compiler_module,
                "_enrich_semantic_records",
                side_effect=orphan_mapping,
            ):
                with self.assertRaises(CompilationError):
                    compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            gate = next(item for item in ledger["invariants"] if item["name"] == "every_safe_line_structurally_mapped")
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["expected"], 1)
            self.assertEqual(gate["actual"], 0)
            self.assertFalse((output / "manifest.json").exists())

    def test_missing_parser_owned_structural_root_fails_both_denominators(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"notes.txt": "A safe source line.\n"})
            output = base / "failed"
            original = compiler_module._enrich_semantic_records

            def remove_root(*args: object, **kwargs: object) -> None:
                original(*args, **kwargs)
                records = args[0]
                assert isinstance(records, dict)
                records["structural_entities"].clear()

            with mock.patch.object(
                compiler_module,
                "_enrich_semantic_records",
                side_effect=remove_root,
            ):
                with self.assertRaises(CompilationError):
                    compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            root_gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "every_safe_parsed_source_has_one_structural_root"
            )
            line_gate = next(
                item for item in ledger["invariants"] if item["name"] == "every_safe_line_structurally_mapped"
            )
            self.assertFalse(root_gate["passed"])
            self.assertEqual((root_gate["expected"], root_gate["actual"]), (1, 0))
            self.assertFalse(line_gate["passed"])
            self.assertEqual((line_gate["expected"], line_gate["actual"]), (1, 0))
            self.assertFalse((output / "manifest.json").exists())

    def test_gui_dossiers_use_only_structural_and_explicit_design_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(
                repository,
                {
                    ".design-sync/config.json": json.dumps(
                        {
                            "projectId": "fixture-design-project",
                            "entry": "./webapp/frontend/ds.entry.ts",
                            "cssEntry": "src/theme.css",
                            "dtsPropsFor": {"Card": "label: string; onSelect?: () => void;"},
                            "componentSrcMap": {"Card": "src/Card.test.tsx"},
                        },
                        indent=2,
                    )
                    + "\n",
                    "webapp/frontend/ds.entry.ts": 'export { Card } from "./src/Card.test";\n',
                    "webapp/frontend/src/theme.css": ":root { --accent: #4f46e5; }\n",
                    "webapp/frontend/src/Card.test.tsx": (
                        'import "./theme.css";\n'
                        "export function Card({ label }: { label: string }) {\n"
                        "  return <button aria-label={label} onClick={() => undefined}>{label}</button>;\n"
                        "}\n"
                        "export function Screen() {\n"
                        '  return <Route path="/card" element={<Card label="Ready" />} />;\n'
                        "}\n"
                        'test("card", () => Card({ label: "Ready" }));\n'
                    ),
                    "webapp/frontend/visual-e2e/design-cards.visual.spec.ts": (
                        "const EXPECTED_VARIANTS = {\n"
                        '  Card: ["Default"],\n'
                        "};\n"
                        'test("visual manifest", () => EXPECTED_VARIANTS.Card);\n'
                    ),
                    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Card.png": b"\x89PNG\r\n\x1a\nfixture",
                    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64/Card-728.png": b"\x89PNG\r\n\x1a\nfixture-728",
                },
            )
            output = base / "compiled"
            compile_repository(repository, output)
            validate_compiler_output(output)

            components = group_records(output, "components")
            routes = group_records(output, "routes")
            card = next(
                row
                for row in components
                if row.get("name") == "Card" and row.get("entity_type") == "jsx_component_symbol"
            )
            dossier = card["gui_dossier"]
            expected_fields = set(compiler_module.GUI_DOSSIER_FIELDS)
            self.assertTrue(expected_fields.issubset(dossier))
            self.assertEqual(dossier["field_count"], len(expected_fields))
            self.assertEqual(dossier["evidence_state"], "explicitly_linked")
            self.assertEqual(dossier["props_contract"]["state"], "explicitly_linked")
            self.assertEqual(dossier["design_sync_receipt"]["state"], "structural_only")
            self.assertIn(
                "design_sync_configuration_is_not_a_sync_or_served_hash_receipt",
                dossier["design_sync_receipt"]["unresolved_reasons"],
            )
            self.assertEqual(dossier["visual_baseline"]["state"], "structural_only")
            self.assertEqual(dossier["responsive_behavior"]["state"], "structural_only")
            self.assertEqual(dossier["user_actions"]["state"], "structural_only")
            self.assertEqual(dossier["accessibility"]["state"], "structural_only")
            self.assertEqual(dossier["tests"]["state"], "structural_only")
            self.assertEqual(dossier["white_label_inputs"]["state"], "not_evidenced")
            self.assertTrue(dossier["source_citation"]["start_line"])
            self.assertTrue(all(field["gap_ids"] for name, field in dossier.items() if name in expected_fields))
            self.assertTrue(routes)
            self.assertTrue(all(row["gui_dossier"]["state_model"]["state"] == "not_evidenced" for row in routes))

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            gui_gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "every_gui_surface_has_standardized_evidence_honest_dossier"
            )
            self.assertTrue(gui_gate["passed"])
            self.assertEqual(gui_gate["expected"], len(components) + len(routes))
            self.assertEqual(gui_gate["actual"], gui_gate["expected"])
            field_states = ledger["semantic_accounting"]["gui_dossier_field_state_counts"]
            self.assertEqual(sum(field_states.values()), gui_gate["expected"] * len(expected_fields))

    def test_gui_dossier_coverage_gate_fails_closed_when_one_surface_is_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(
                repository,
                {"api.py": "@app.get('/health')\ndef health():\n    return {'ok': True}\n"},
            )
            output = base / "failed"
            original = compiler_module._enrich_gui_dossiers

            def remove_dossier(*args: object, **kwargs: object) -> None:
                original(*args, **kwargs)
                records = args[0]
                assert isinstance(records, dict)
                records["routes"][0].pop("gui_dossier")

            with mock.patch.object(
                compiler_module,
                "_enrich_gui_dossiers",
                side_effect=remove_dossier,
            ):
                with self.assertRaises(CompilationError):
                    compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "every_gui_surface_has_standardized_evidence_honest_dossier"
            )
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["expected"], 1)
            self.assertEqual(gate["actual"], 0)
            self.assertTrue(ledger["hard_failure"])
            self.assertFalse((output / "manifest.json").exists())

    def test_exact_compile_rejects_index_flags_that_hide_worktree_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"notes.txt": "Committed source.\n"})
            git(repository, "update-index", "--assume-unchanged", "notes.txt")
            write(repository, "notes.txt", "Hidden worktree change.\n")
            self.assertEqual(git(repository, "status", "--porcelain=v1"), "")

            output = base / "failed"
            with self.assertRaisesRegex(CompilationError, "index flag"):
                compile_repository(repository, output)

            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["hard_failure"])
            self.assertTrue(any("index flag" in item for item in ledger["fatal_errors"]))
            self.assertFalse((output / "manifest.json").exists())

    def test_compiler_blocks_publication_when_claim_algebra_rejects_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"README.md": "# Claim gate\n"})
            output = base / "failed"

            with mock.patch("compiler.compiler.validate_claims", return_value=("forced_violation",)) as validator:
                with self.assertRaises(CompilationError) as caught:
                    compile_repository(repository, output)

            validator.assert_called_once()
            self.assertIn("claim_integrity:forced_violation", caught.exception.errors)
            self.assertFalse((output / "manifest.json").exists())

    def test_python_parser_failure_emits_ledger_without_partial_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"broken.py": "def broken(:\n    pass\n"})
            output = base / "failed"
            with self.assertRaises(CompilationError):
                compile_repository(repository, output)
            self.assertTrue((output / "completeness.json").is_file())
            self.assertTrue((output / "failure.json").is_file())
            self.assertFalse((output / "manifest.json").exists())
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["hard_failure"])
            self.assertEqual(ledger["parsing"]["status_counts"]["parser_error"], 1)
            self.assertFalse(
                next(item for item in ledger["invariants"] if item["name"] == "no_silent_parser_failure")["passed"]
            )
            with self.assertRaises(SchemaValidationError):
                validate_compiler_output(output)

    def test_schema_rejects_an_incomplete_semantic_acceptance_gate_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"README.md": "# Gate registry\n"})
            output = base / "compiled"
            compile_repository(repository, output)
            ledger_path = output / "completeness.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["acceptance_gates"] = ledger["acceptance_gates"][:-1]
            ledger_path.write_text(
                json.dumps(ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaises(SchemaValidationError):
                validate_compiler_output(output)

    def test_schema_validation_rejects_missing_graphify_exclusion_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            commit = initialize_repository(repository, {"README.md": "# Graph ledger\n"})
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": commit,
                        "nodes": [
                            {"id": "safe", "source_file": "README.md", "_origin": "ast"},
                            {"id": "secret", "source_file": "client/secret.txt", "_origin": "ast"},
                        ],
                        "links": [
                            {"source": "safe", "target": "secret", "relation": "hidden"},
                        ],
                        "hyperedges": [],
                    },
                    sort_keys=True,
                ),
            )
            output = base / "compiled"
            compile_repository(repository, output)
            validate_compiler_output(output)

            metadata_path = output / "graphify-metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            out_of_range = json.loads(json.dumps(metadata))
            out_of_range["excluded_node_dispositions"][0]["raw_index"] = 999
            metadata_path.write_text(
                json.dumps(out_of_range, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(
                SchemaValidationError,
                "disposition reconciliation",
            ):
                validate_compiler_output(output)

            metadata["excluded_node_dispositions"].clear()
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(
                SchemaValidationError,
                "disposition reconciliation",
            ):
                validate_compiler_output(output)

    def test_typescript_failure_is_stable_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"webapp/src/broken.ts": "export const value = ;\n"})
            output = base / "failed"
            with self.assertRaises(CompilationError) as caught:
                compile_repository(repository, output)
            message = " ".join(caught.exception.errors)
            self.assertIn("SYNTAX_DIAGNOSTIC", message)
            self.assertIn("webapp/src/broken.ts:1", message)
            self.assertNotIn(str(repository), message)
            self.assertFalse((output / "manifest.json").exists())

    def test_metadata_only_path_is_never_line_mapped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(
                repository,
                {
                    "README.md": "# Public\n",
                    "docs/vault/private.md": "DO-NOT-PUBLISH-THIS-LINE\n",
                },
            )
            output = base / "output"
            compile_repository(repository, output)
            files = {record["path"]: record for record in group_records(output, "files")}
            private = files["docs/vault/private.md"]
            self.assertEqual(private["privacy_exposure"], "metadata_only")
            self.assertIsNone(private["content_digest"])
            self.assertFalse(any(row["file_id"] == private["id"] for row in group_records(output, "lines")))
            self.assertFalse(any(row["file_id"] == private["id"] for row in group_records(output, "source_text")))
            self.assertNotIn(b"DO-NOT-PUBLISH-THIS-LINE", b"".join(output_bytes(output).values()))

    def test_binary_payload_is_metadata_only_and_keeps_a_git_object_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"docs/card.png": b"\x89PNG\r\n\x1a\nfixture"})
            output = base / "output"
            compile_repository(repository, output)

            file_record = group_records(output, "files")[0]
            binary = group_records(output, "binaries")[0]
            self.assertEqual(binary["entity_type"], "binary")
            self.assertEqual(file_record["privacy_exposure"], "metadata_only")
            self.assertEqual(file_record["content_source"], "metadata_only_git_object")
            self.assertIsNone(file_record["content_digest"])
            self.assertEqual(binary["git_blob_oid"], file_record["git_blob_oid"])
            self.assertIsNone(binary["content_digest"])
            self.assertEqual(binary["inspection_mode"], "git_object_digest_and_metadata_only")
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["privacy"]["binary_payload_scan"]["inventory_only_files"], 1)
            gate = next(
                item
                for item in ledger["acceptance_gates"]
                if item["name"] == "every_binary_has_format_aware_privacy_review"
            )
            self.assertFalse(gate["passed"])

    def test_exact_tracked_binary_review_stays_pending_authentication_and_keeps_payload_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            payload = one_pixel_png()
            basis = initialize_repository(repository, {"docs/card.png": payload})
            commit_binary_receipt(repository, basis, {"docs/card.png": payload})
            output = base / "output"

            compile_repository(repository, output)
            validate_compiler_output(output)

            file_record = next(row for row in group_records(output, "files") if row["path"] == "docs/card.png")
            binary = group_records(output, "binaries")[0]
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            scan = ledger["privacy"]["binary_payload_scan"]
            gate = next(
                item
                for item in ledger["acceptance_gates"]
                if item["name"] == "every_binary_has_format_aware_privacy_review"
            )

            self.assertEqual(scan["status"], "incomplete")
            self.assertEqual(scan["expected_files"], 1)
            self.assertEqual(scan["receipt_records"], 1)
            self.assertEqual(scan["identity_matched_files"], 1)
            self.assertEqual(scan["automated_format_passed_files"], 1)
            self.assertEqual(scan["automated_format_pending_files"], 0)
            self.assertEqual(scan["claimed_independent_contextual_passed_files"], 1)
            self.assertEqual(scan["independent_contextual_passed_files"], 0)
            self.assertEqual(scan["accepted_files"], 0)
            self.assertEqual(scan["format_counts"], {"gzip_tsv": 0, "png": 1, "unsupported": 0})
            self.assertEqual(scan["error_codes"], ["binary_review_reviewer_authentication_pending"])
            self.assertTrue(scan["review_basis_is_ancestor"])
            self.assertEqual(
                scan["reviewer_custody"],
                {
                    "status": "pending_trusted_external_attestation",
                    "required_mechanism": "detached_signature_with_trusted_public_key",
                    "trusted_public_key_configured": False,
                    "detached_signature_present": False,
                    "detached_signature_verified": False,
                    "authenticated_reviewer_kind": None,
                    "authenticated_files": 0,
                    "receipt_claims_trusted": False,
                },
            )
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["expected"], 1)
            self.assertEqual(gate["actual"], 0)
            self.assertEqual(file_record["privacy_exposure"], "metadata_only")
            self.assertIsNone(file_record["content_digest"])
            self.assertIsNone(binary["content_digest"])
            self.assertEqual(binary["inspection_mode"], "git_object_digest_and_metadata_only")
            self.assertFalse(any(row["path"] == "docs/card.png" for row in group_records(output, "source_text")))
            self.assertNotIn(payload, b"".join(output_bytes(output).values()))

            other_gates = [item for item in ledger["acceptance_gates"] if item["name"] != gate["name"]]
            self.assertTrue(any(item["passed"] is False for item in other_gates))

    def test_exact_gzip_tsv_review_uses_classifier_logical_media_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            path = "cisco_toolkit/data/oui_registry.tsv.gz"
            payload = gzip.compress(b"00000C\t24\tExample Vendor\n", mtime=0)
            basis = initialize_repository(repository, {path: payload})
            commit_binary_receipt(repository, basis, {path: payload})
            output = base / "output"

            compile_repository(repository, output)
            validate_compiler_output(output)

            file_record = next(row for row in group_records(output, "files") if row["path"] == path)
            binary = next(row for row in group_records(output, "binaries") if row["path"] == path)
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            scan = ledger["privacy"]["binary_payload_scan"]
            self.assertEqual(file_record["media_type"], "text/tab-separated-values")
            self.assertEqual(binary["media_type"], "text/tab-separated-values")
            self.assertEqual(scan["status"], "incomplete")
            self.assertEqual(scan["identity_matched_files"], 1)
            self.assertEqual(scan["automated_format_passed_files"], 1)
            self.assertEqual(scan["accepted_files"], 0)
            self.assertEqual(scan["error_codes"], ["binary_review_reviewer_authentication_pending"])

    def test_exact_compile_rejects_changed_or_missing_review_basis_blob(self) -> None:
        for name, basis_files in (
            ("changed", {"docs/card.png": one_pixel_png()}),
            ("missing", {"README.md": "# Basis without binary\n"}),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                repository = base / "repo"
                basis = initialize_repository(repository, basis_files)
                current_payload = one_pixel_png(compression_level=1)
                write(repository, "docs/card.png", current_payload)
                git(repository, "add", "docs/card.png")
                git(repository, "commit", "-qm", "current binary")
                current_commit = git(repository, "rev-parse", "HEAD")
                receipt = tracked_binary_receipt(repository, current_commit, {"docs/card.png": current_payload})
                receipt["review_basis_commit"] = basis
                write(
                    repository,
                    binary_review_module.RECEIPT_PATH,
                    canonical_json(receipt),
                )
                git(repository, "add", binary_review_module.RECEIPT_PATH)
                git(repository, "commit", "-qm", "stale basis receipt")

                output = base / "output"
                compile_repository(repository, output)
                validate_compiler_output(output)
                scan = json.loads((output / "completeness.json").read_text(encoding="utf-8"))["privacy"][
                    "binary_payload_scan"
                ]
                self.assertEqual(scan["status"], "invalid")
                self.assertEqual(scan["identity_matched_files"], 0)
                self.assertIn("binary_review_receipt_identity_mismatch", scan["error_codes"])
                self.assertEqual(scan["accepted_files"], 0)

    def test_tracked_binary_review_owner_is_exact_current_46_member_denominator(self) -> None:
        repository = MASTER_REFERENCE.parent
        receipt_path = repository / binary_review_module.RECEIPT_PATH
        receipt_raw = receipt_path.read_bytes()
        receipt = parse_tracked_binary_review(receipt_raw)
        tracked_paths = [
            value.decode("utf-8", errors="strict")
            for value in git_bytes(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
            if value
        ]
        binary_paths = sorted(path for path in tracked_paths if path.lower().endswith((".png", ".tsv.gz")))
        descriptors = []
        for path in binary_paths:
            descriptors.append(
                {
                    "path": path,
                    "git_blob_oid": git(repository, "rev-parse", f"HEAD:{path}"),
                    "media_type": "image/png" if path.lower().endswith(".png") else "text/tab-separated-values",
                    "raw": git_bytes(repository, "cat-file", "blob", f"HEAD:{path}"),
                }
            )

        summary = evaluate_tracked_binary_review(
            receipt_raw,
            descriptors,
            receipt_git_blob_oid="0" * 40,
            review_basis_is_ancestor=lambda basis: git(repository, "merge-base", "--is-ancestor", basis, "HEAD") == "",
            review_basis_blobs=lambda basis, paths: review_basis_blobs(repository, basis, paths),
        )

        self.assertEqual([row["path"] for row in receipt["records"]], binary_paths)
        self.assertEqual(len(binary_paths), 46)
        self.assertEqual(summary["format_counts"], {"gzip_tsv": 2, "png": 44, "unsupported": 0})
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(summary["identity_matched_files"], 46)
        self.assertEqual(summary["automated_format_passed_files"], 44)
        self.assertEqual(summary["automated_format_pending_files"], 2)
        self.assertEqual(summary["claimed_independent_contextual_passed_files"], 46)
        self.assertEqual(summary["independent_contextual_passed_files"], 0)
        self.assertEqual(summary["accepted_files"], 0)
        self.assertEqual(
            summary["error_codes"],
            [
                "binary_review_automated_format_pending_unsupported_png_ancillary",
                "binary_review_reviewer_authentication_pending",
            ],
        )

    def test_binary_review_join_rejects_missing_orphan_duplicate_wrong_stale_and_malformed_rows(self) -> None:
        payload = one_pixel_png()
        digest = hashlib.sha256(payload).hexdigest()
        base_record = {
            "path": "docs/card.png",
            "git_blob_oid": git_blob_oid(payload),
            "raw_sha256": digest,
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
        descriptors = [
            {
                "path": base_record["path"],
                "git_blob_oid": base_record["git_blob_oid"],
                "media_type": base_record["media_type"],
                "raw": payload,
            }
        ]

        def receipt(records: list[dict[str, object]], *, basis: str = "2" * 40) -> dict[str, object]:
            return {
                "schema_version": "tracked-binary-review/1",
                "receipt_kind": "tracked_repository_binary_privacy_review",
                "review_basis_commit": basis,
                "binary_set_digest": binary_set_digest(records) if records else "0" * 64,
                "records": records,
            }

        orphan = copy.deepcopy(base_record)
        orphan["path"] = "docs/orphan.png"
        orphan["git_blob_oid"] = "3" * 40
        cases: list[tuple[str, dict[str, object], bool, str]] = [
            (
                "missing",
                receipt([]),
                True,
                "binary_review_receipt_malformed",
            ),
            (
                "orphan",
                receipt(sorted([copy.deepcopy(base_record), orphan], key=lambda row: str(row["path"]))),
                True,
                "binary_review_receipt_membership_mismatch",
            ),
            (
                "duplicate",
                receipt([copy.deepcopy(base_record), copy.deepcopy(base_record)]),
                True,
                "binary_review_receipt_malformed",
            ),
            (
                "wrong_blob",
                receipt([{**copy.deepcopy(base_record), "git_blob_oid": "4" * 40}]),
                True,
                "binary_review_receipt_identity_mismatch",
            ),
            (
                "stale_basis",
                receipt([copy.deepcopy(base_record)]),
                False,
                "binary_review_receipt_review_basis_not_ancestor",
            ),
            (
                "wrong_evidence",
                receipt(
                    [
                        {
                            **copy.deepcopy(base_record),
                            "automated_format_evidence": {
                                **copy.deepcopy(base_record["automated_format_evidence"]),
                                "width": 2,
                            },
                        }
                    ]
                ),
                True,
                "binary_review_receipt_format_evidence_mismatch",
            ),
            (
                "context_block",
                receipt(
                    [
                        {
                            **copy.deepcopy(base_record),
                            "independent_review": {
                                **copy.deepcopy(base_record["independent_review"]),
                                "verdict": "block",
                            },
                        }
                    ]
                ),
                True,
                "binary_review_receipt_independent_verdict_not_passed",
            ),
        ]
        for name, candidate, ancestor, expected_code in cases:
            with self.subTest(name=name):
                raw = canonical_json(candidate)
                summary = evaluate_tracked_binary_review(
                    raw,
                    descriptors,
                    receipt_git_blob_oid="5" * 40,
                    review_basis_is_ancestor=lambda _basis, answer=ancestor: answer,
                    review_basis_blobs=lambda _basis, paths: {path: (git_blob_oid(payload), payload) for path in paths},
                )
                self.assertNotEqual(summary["status"], "passed")
                self.assertIn(expected_code, summary["error_codes"])
                self.assertEqual(summary["accepted_files"], 0)

        for invented_reference in (
            "attestation:invented",
            "attestation:c:/users/foreign-owner/private",
            "decoded-tsv-sha256:" + ("0" * 64),
        ):
            invented_claim = copy.deepcopy(base_record)
            invented_claim["independent_review"]["evidence_references"] = [invented_reference]
            invented_raw = canonical_json(receipt([invented_claim]))
            with self.subTest(reference=invented_reference), self.assertRaises(BinaryReviewFailure) as caught:
                parse_tracked_binary_review(invented_raw)
            self.assertEqual(str(caught.exception), "binary_review_receipt_malformed")
            self.assertNotIn(invented_reference, str(caught.exception))

        marker = "C:/Users/ConfidentialOwner/Desktop/private"
        malformed = canonical_json({**receipt([copy.deepcopy(base_record)]), marker: marker})
        with self.assertRaises(BinaryReviewFailure) as caught:
            parse_tracked_binary_review(malformed)
        self.assertEqual(str(caught.exception), "binary_review_receipt_malformed")
        self.assertNotIn(marker, str(caught.exception))

    def test_binary_review_basis_blob_join_rejects_changed_missing_and_untrusted_history(self) -> None:
        basis_payload = one_pixel_png()
        current_payload = one_pixel_png(compression_level=1)
        current_oid = git_blob_oid(current_payload)
        basis_oid = git_blob_oid(basis_payload)
        self.assertNotEqual(basis_oid, current_oid)
        current_evidence = inspect_png(current_payload)
        record = {
            "path": "docs/card.png",
            "git_blob_oid": current_oid,
            "raw_sha256": hashlib.sha256(current_payload).hexdigest(),
            "raw_bytes": len(current_payload),
            "media_type": "image/png",
            "format": "png",
            "automated_format_evidence": current_evidence,
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
            "review_basis_commit": "2" * 40,
            "binary_set_digest": binary_set_digest([record]),
            "records": [record],
        }
        descriptors = [
            {
                "path": record["path"],
                "git_blob_oid": current_oid,
                "media_type": "image/png",
                "raw": current_payload,
            }
        ]

        marker = "C:/Users/Foreign.Owner/private-basis"
        cases = {
            "changed": lambda _basis, paths: {paths[0]: (basis_oid, basis_payload)},
            "missing": lambda _basis, _paths: {},
            "extra": lambda _basis, paths: {
                paths[0]: (current_oid, current_payload),
                marker: (current_oid, current_payload),
            },
            "malformed": lambda _basis, paths: {paths[0]: (marker, marker.encode("utf-8"))},
            "exception": lambda _basis, _paths: (_ for _ in ()).throw(RuntimeError(marker)),
        }
        for name, resolver in cases.items():
            with self.subTest(name=name):
                summary = evaluate_tracked_binary_review(
                    canonical_json(receipt),
                    descriptors,
                    receipt_git_blob_oid="5" * 40,
                    review_basis_is_ancestor=lambda _basis: True,
                    review_basis_blobs=resolver,
                )
                self.assertEqual(summary["status"], "invalid")
                self.assertEqual(summary["identity_matched_files"], 0)
                self.assertIn("binary_review_receipt_identity_mismatch", summary["error_codes"])
                self.assertNotIn(marker, json.dumps(summary, sort_keys=True))

        ancestry_error = evaluate_tracked_binary_review(
            canonical_json(receipt),
            descriptors,
            receipt_git_blob_oid="5" * 40,
            review_basis_is_ancestor=lambda _basis: (_ for _ in ()).throw(RuntimeError(marker)),
            review_basis_blobs=lambda _basis, _paths: (_ for _ in ()).throw(AssertionError("not reached")),
        )
        self.assertEqual(ancestry_error["status"], "invalid")
        self.assertIn("binary_review_receipt_review_basis_not_ancestor", ancestry_error["error_codes"])
        self.assertNotIn(marker, json.dumps(ancestry_error, sort_keys=True))

        newline_path = copy.deepcopy(record)
        newline_path["path"] = "docs/private\ncard.png"
        newline_receipt = {**receipt, "records": [newline_path], "binary_set_digest": binary_set_digest([newline_path])}
        with self.assertRaises(BinaryReviewFailure) as caught:
            parse_tracked_binary_review(canonical_json(newline_receipt))
        self.assertEqual(str(caught.exception), "binary_review_receipt_malformed")

    def test_png_format_review_rejects_crc_order_framing_trailing_and_secret_metadata(self) -> None:
        valid = one_pixel_png()
        self.assertEqual(inspect_png(valid)["decoded_scanline_bytes"], 5)

        def ancillary_png(kind: bytes, data: bytes) -> bytes:
            ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            idat = png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
            return b"\x89PNG\r\n\x1a\n" + ihdr + png_chunk(kind, data) + idat + png_chunk(b"IEND", b"")

        bad_crc = bytearray(valid)
        bad_crc[-1] ^= 1
        bad_order = (
            b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
            + png_chunk(b"PLTE", b"\x00\x00\x00")
            + png_chunk(b"IEND", b"")
        )
        secret = ("-----BEGIN " + "PRIVATE KEY-----").encode()
        invalid = {
            "crc": bytes(bad_crc),
            "order": bad_order,
            "idat_multi_stream": one_pixel_png(idat_suffix=zlib.compress(b"extra")),
            "trailing": valid + b"trailing",
        }
        for name, candidate in invalid.items():
            with self.subTest(name=name), self.assertRaises(BinaryReviewFailure) as caught:
                inspect_png(candidate)
            self.assertEqual(str(caught.exception), "binary_format_invalid")
            self.assertNotIn(secret.decode(), str(caught.exception))

        unsupported_channels = {
            "text": one_pixel_png(text_payload=secret),
            "compressed_iccp": ancillary_png(b"iCCP", b"profile\0\0" + zlib.compress(secret)),
            "exif": ancillary_png(b"eXIf", b"II*\x00" + secret),
            "private_unknown_vpag": ancillary_png(b"vpAg", secret),
        }
        for name, candidate in unsupported_channels.items():
            with self.subTest(name=name), self.assertRaises(BinaryReviewFailure) as caught:
                inspect_png(candidate)
            self.assertEqual(
                str(caught.exception),
                "binary_review_automated_format_pending_unsupported_png_ancillary",
            )
            self.assertNotIn(secret.decode(), str(caught.exception))

    def test_gzip_tsv_receipt_uses_classifier_logical_media_type(self) -> None:
        raw = gzip.compress(b"00000C\t24\tExample Vendor\n", mtime=0)
        evidence = inspect_gzip_tsv("cisco_toolkit/data/oui_registry.tsv.gz", raw)
        record = {
            "path": "cisco_toolkit/data/oui_registry.tsv.gz",
            "git_blob_oid": "1" * 40,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes": len(raw),
            "media_type": "text/tab-separated-values",
            "format": "gzip_tsv",
            "automated_format_evidence": evidence,
            "independent_review": {
                "reviewer_kind": "independent_agent",
                "reviewer_role": "binary_privacy_verifier",
                "independent_from_proposer": True,
                "review_scope": "decoded_tsv_rows_and_context",
                "evidence_references": [
                    f"decoded-tsv-sha256:{evidence['uncompressed_sha256']}",
                    "privacy-scan:forbidden-local-generic-identities",
                    "registry-validation:retained-source-and-runtime-loader",
                ],
                "verdict": "pass",
            },
        }

        def encoded_receipt(candidate: dict[str, object]) -> bytes:
            return canonical_json(
                {
                    "schema_version": "tracked-binary-review/1",
                    "receipt_kind": "tracked_repository_binary_privacy_review",
                    "review_basis_commit": "2" * 40,
                    "binary_set_digest": binary_set_digest([candidate]),
                    "records": [candidate],
                }
            )

        parsed = parse_tracked_binary_review(encoded_receipt(record))
        self.assertEqual(parsed["records"][0]["media_type"], "text/tab-separated-values")

        transport_typed = {**copy.deepcopy(record), "media_type": "application/gzip"}
        with self.assertRaises(BinaryReviewFailure) as caught:
            parse_tracked_binary_review(encoded_receipt(transport_typed))
        self.assertEqual(str(caught.exception), "binary_review_receipt_malformed")

    def test_gzip_tsv_review_rejects_multiple_members_trailing_crc_bomb_schema_utf8_and_secret(self) -> None:
        payload = b"00000C\t24\tExample Vendor\n"
        valid = gzip.compress(payload, mtime=0)
        evidence = inspect_gzip_tsv("cisco_toolkit/data/oui_registry.tsv.gz", valid)
        self.assertEqual(evidence["row_count"], 1)
        self.assertEqual(evidence["tsv_header"], list(binary_review_module.OUI_TSV_HEADER))

        wrong_crc = bytearray(valid)
        wrong_crc[-8] ^= 1
        secret = ("-----BEGIN " + "PRIVATE KEY-----").encode()
        optional_header = bytearray(valid[:10])
        optional_header[3] = 0x1E
        optional_fields = struct.pack("<H", len(secret)) + secret + secret + b"\0" + secret + b"\0"
        optional_prefix = bytes(optional_header) + optional_fields
        combined_optional_metadata = (
            optional_prefix + struct.pack("<H", binascii.crc32(optional_prefix) & 0xFFFF) + valid[10:]
        )
        local_identity = b"C:\\Users\\foreign-owner\\private"
        invalid = {
            "multiple_members": valid + valid,
            "trailing": valid + b"x",
            "crc": bytes(wrong_crc),
            "schema": gzip.compress(b"not\ta\tvalid\textra\n", mtime=0),
            "overlay_schema": gzip.compress(b"80\ttcp\thttp\t[]\t\t0\t\tiana\tiana\t\tunowned\tnone\n", mtime=0),
            "utf8": gzip.compress(b"00000C\t24\t\xff\n", mtime=0),
            "secret": gzip.compress(b"00000C\t24\t" + secret + b"\n", mtime=0),
            "combined_optional_metadata": combined_optional_metadata,
            "generic_local_identity": gzip.compress(b"00000C\t24\t" + local_identity + b"\n", mtime=0),
        }
        for name, candidate in invalid.items():
            with self.subTest(name=name), self.assertRaises(BinaryReviewFailure) as caught:
                inspect_gzip_tsv("cisco_toolkit/data/oui_registry.tsv.gz", candidate)
            self.assertEqual(str(caught.exception), "binary_format_invalid")
            self.assertNotIn(secret.decode(), str(caught.exception))
            self.assertNotIn(local_identity.decode(), str(caught.exception))

        with (
            mock.patch.object(binary_review_module, "MAX_GZIP_DECOMPRESSED_BYTES", 16),
            self.assertRaises(BinaryReviewFailure) as caught,
        ):
            inspect_gzip_tsv(
                "cisco_toolkit/data/oui_registry.tsv.gz",
                gzip.compress(b"00000C\t24\t" + (b"A" * 64) + b"\n", mtime=0),
            )
        self.assertEqual(str(caught.exception), "binary_format_invalid")

    def test_high_confidence_secret_material_fails_without_retaining_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            secret_header = "-----BEGIN " + "PRIVATE KEY-----\n"
            initialize_repository(repository, {"README.md": f"# Unsafe\n{secret_header}"})
            output = base / "failed"

            with self.assertRaises(CompilationError) as caught:
                compile_repository(repository, output)

            self.assertIn("forbidden-content rule private_key_material", " ".join(caught.exception.errors))
            ledger_text = (output / "completeness.json").read_text(encoding="utf-8")
            ledger = json.loads(ledger_text)
            scan = ledger["privacy"]["forbidden_content_scan"]
            self.assertEqual(scan["status"], "failed")
            self.assertEqual(scan["findings_count"], 1)
            self.assertFalse(scan["matched_values_retained"])
            self.assertNotIn(secret_header.strip(), ledger_text)
            self.assertFalse((output / "manifest.json").exists())

    def test_graphify_edge_cannot_smuggle_private_path_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            commit = initialize_repository(repository, {"README.md": "# Safe\n"})
            graph = {
                "built_at_commit": commit,
                "nodes": [
                    {"id": "a", "source_file": "README.md", "source_location": "L1", "_origin": "ast"},
                    {"id": "b", "source_file": "README.md", "source_location": "L1", "_origin": "ast"},
                ],
                "links": [
                    {
                        "source": "a",
                        "target": "b",
                        "relation": "calls",
                        "confidence": "extracted",
                        "source_file": "docs/vault/private.md",
                        "source_location": "CLIENT-PATH-L1",
                    }
                ],
                "hyperedges": [],
            }
            write(repository, "graphify-out/graph.json", json.dumps(graph, sort_keys=True))
            output = base / "failed"

            with self.assertRaises(CompilationError) as caught:
                compile_repository(repository, output)

            self.assertIn("retained edge carries an untracked, private", " ".join(caught.exception.errors))
            self.assertFalse((output / "manifest.json").exists())

    def test_graphify_huge_confidence_fails_with_fixed_non_echoing_compiler_ledger(self) -> None:
        for huge_score in (10**1000, -(10**1000)):
            with self.subTest(negative=huge_score < 0), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                repository = base / "repo"
                commit = initialize_repository(repository, {"README.md": "# Safe\n"})
                graph = {
                    "built_at_commit": commit,
                    "nodes": [
                        {"id": "a", "source_file": "README.md", "source_location": "L1", "_origin": "ast"},
                        {"id": "b", "source_file": "README.md", "source_location": "L2", "_origin": "ast"},
                    ],
                    "links": [
                        {
                            "source": "a",
                            "target": "b",
                            "relation": "calls",
                            "confidence": "extracted",
                            "confidence_score": huge_score,
                            "source_file": "README.md",
                            "source_location": "L1",
                        }
                    ],
                    "hyperedges": [],
                }
                write(repository, "graphify-out/graph.json", json.dumps(graph, sort_keys=True))
                output = base / "failed"

                with self.assertRaises(CompilationError) as caught:
                    compile_repository(repository, output)

                fixed_reason = "edge confidence_score must be null or a finite number from zero to one"
                self.assertIn(fixed_reason, " ".join(caught.exception.errors))
                ledger_text = (output / "completeness.json").read_text(encoding="utf-8")
                self.assertIn(fixed_reason, ledger_text)
                self.assertNotIn(str(abs(huge_score))[:80], ledger_text)
                self.assertFalse((output / "manifest.json").exists())

    def test_graphify_deep_json_nesting_fails_with_fixed_non_echoing_compiler_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"README.md": "# Safe\n"})
            marker = "c_users_foreign_owner_desktop_checkout"
            write(repository, "graphify-out/graph.json", '{"nodes":[],"links":[]}')
            output = base / "failed"

            with mock.patch.object(
                graphify_module.json,
                "loads",
                side_effect=RecursionError(marker),
            ):
                with self.assertRaises(CompilationError) as caught:
                    compile_repository(repository, output)

            fixed_reason = "JSON nesting exceeds the parser limit"
            self.assertIn(fixed_reason, " ".join(caught.exception.errors))
            ledger_text = (output / "completeness.json").read_text(encoding="utf-8")
            self.assertIn(fixed_reason, ledger_text)
            self.assertNotIn(marker, ledger_text)
            self.assertFalse((output / "manifest.json").exists())

    def test_graphify_scalar_channels_are_bounded_and_never_stringify_containers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            marker = "c_users_foreign_owner_desktop_checkout"
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {
                                "id": "safe",
                                "source_file": "safe.py",
                                "source_location": "9" * 65,
                                "file_type": {"private": marker},
                                "metadata": {"language": [marker], "kind": "\ud800"},
                                "_origin": {"private": marker},
                            },
                            {
                                "id": 7,
                                "source_file": "safe.py",
                                "source_location": 2,
                                "_origin": "ast",
                            },
                        ],
                        "links": [
                            {
                                "source": "safe",
                                "target": 7,
                                "confidence": {"private": marker},
                                "relation": [marker],
                                "source_file": "safe.py",
                                "source_location": {"private": marker},
                            }
                        ],
                        "hyperedges": [],
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            )
            metadata, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:" + "c" * 24},
            )
            self.assertEqual((len(nodes), len(edges)), (2, 1))
            first = next(node for node in nodes if node["source_location"] == "")
            self.assertEqual((first["file_type"], first["language"], first["kind"]), ("", "", ""))
            self.assertEqual(first["origin"], "undisclosed")
            self.assertIn(
                "graphify_node_source_location_outside_bounded_coordinate_domain",
                first["unresolved_reasons"],
            )
            self.assertEqual(edges[0]["extraction_mode"], "undisclosed")
            self.assertEqual(edges[0]["relation"], "related_to")
            self.assertEqual(edges[0]["source_location"], "")
            outward = json.dumps({"metadata": metadata, "nodes": nodes, "edges": edges}, sort_keys=True)
            self.assertNotIn(marker, outward)
            self.assertNotIn("\\ud800", outward)

            invalid_identifiers = ({"id": marker}, [marker], "\ud800", 10**1000, True, "")
            for invalid in invalid_identifiers:
                with self.subTest(invalid_type=type(invalid).__name__):
                    write(
                        repository,
                        "graphify-out/graph.json",
                        json.dumps(
                            {
                                "nodes": [{"id": invalid, "source_file": "safe.py"}],
                                "links": [],
                            },
                            ensure_ascii=True,
                        ),
                    )
                    with self.assertRaises(GraphifyFailure) as caught:
                        project_graphify(repository, "a" * 40, "b" * 64, {"safe.py": "file"})
                    self.assertIn("node id must be nonempty text or a safe integer", str(caught.exception))
                    self.assertNotIn(marker, str(caught.exception))
            for invalid in ({"source": marker}, [marker], "\ud800", 10**1000, True, None):
                with self.subTest(endpoint_type=type(invalid).__name__):
                    write(
                        repository,
                        "graphify-out/graph.json",
                        json.dumps(
                            {
                                "nodes": [{"id": "safe", "source_file": "safe.py", "_origin": "ast"}],
                                "links": [{"source": invalid, "target": "safe"}],
                            },
                            ensure_ascii=True,
                        ),
                    )
                    with self.assertRaises(GraphifyFailure) as caught:
                        project_graphify(repository, "a" * 40, "b" * 64, {"safe.py": "file"})
                    self.assertIn(
                        "link source id must be nonempty text or a safe integer",
                        str(caught.exception),
                    )
                    self.assertNotIn(marker, str(caught.exception))

    def test_graphify_excluded_record_unread_fields_are_not_receipted_or_echoed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            marker = "c_users_foreign_owner_desktop_checkout"
            deep: object = marker
            for _ in range(70):
                deep = [deep]
            adversaries = (float("nan"), "\ud800", deep)
            for record_type, adversary in (("node", value) for value in adversaries):
                with self.subTest(record_type=record_type, adversary=type(adversary).__name__):
                    write(
                        repository,
                        "graphify-out/graph.json",
                        json.dumps(
                            {
                                "nodes": [
                                    {
                                        "id": "private",
                                        "source_file": "private.py",
                                        "producer_extra": adversary,
                                    }
                                ],
                                "links": [],
                            },
                            ensure_ascii=True,
                        ),
                    )
                    metadata, nodes, edges = project_graphify(repository, "a" * 40, "b" * 64, {})
                    self.assertEqual((len(nodes), len(edges)), (0, 0))
                    outward = json.dumps(metadata, sort_keys=True)
                    self.assertNotIn(marker, outward)
                    self.assertNotIn("producer_extra", outward)
                    self.assertNotIn("raw_record_digest", outward)
            for adversary in adversaries:
                with self.subTest(record_type="edge", adversary=type(adversary).__name__):
                    write(
                        repository,
                        "graphify-out/graph.json",
                        json.dumps(
                            {
                                "nodes": [{"id": "safe", "source_file": "safe.py", "_origin": "ast"}],
                                "links": [
                                    {
                                        "source": "safe",
                                        "target": "missing",
                                        "producer_extra": adversary,
                                    }
                                ],
                            },
                            ensure_ascii=True,
                        ),
                    )
                    metadata, nodes, edges = project_graphify(
                        repository,
                        "a" * 40,
                        "b" * 64,
                        {"safe.py": "urn:atlas:file:" + "c" * 24},
                    )
                    self.assertEqual((len(nodes), len(edges)), (1, 0))
                    outward = json.dumps(metadata, sort_keys=True)
                    self.assertNotIn(marker, outward)
                    self.assertNotIn("producer_extra", outward)
                    self.assertNotIn("raw_record_digest", outward)

    def test_graphify_metadata_shapes_and_nested_string_channels_are_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            write(
                repository,
                "graphify-out/graph.json",
                json.dumps(
                    {
                        "built_at_commit": "a" * 40,
                        "nodes": [
                            {
                                "id": "safe",
                                "source_file": "safe.py",
                                "source_location": "L1",
                                "community": 1,
                                "_origin": "ast",
                            }
                        ],
                        "links": [],
                        "hyperedges": [],
                    }
                ),
            )
            metadata, nodes, edges = project_graphify(
                repository,
                "a" * 40,
                "b" * 64,
                {"safe.py": "urn:atlas:file:" + "c" * 24},
            )
            marker = "benign-private-token-7f3a"

            def extra_key(value: dict[str, object]) -> None:
                value["producer_note"] = marker

            def extra_reason(value: dict[str, object]) -> None:
                value["unresolved_reasons"].append(marker)  # type: ignore[union-attr]

            def origin_key(value: dict[str, object]) -> None:
                value["node_origins"][marker] = 0  # type: ignore[index]

            def community_status(value: dict[str, object]) -> None:
                value["community_dispositions"][0]["status"] = marker  # type: ignore[index]

            def scalar_mismatch(value: dict[str, object]) -> None:
                value["excluded_nodes_unsafe_source"] = 1

            for mutate in (extra_key, extra_reason, origin_key, community_status, scalar_mismatch):
                tampered = copy.deepcopy(metadata)
                mutate(tampered)
                with self.subTest(mutation=mutate.__name__):
                    with self.assertRaises(GraphifyFailure) as caught:
                        graphify_module.validate_graphify_metadata(tampered, nodes, edges)
                    self.assertNotIn(marker, str(caught.exception))

    def test_graphify_absent_receipt_preserves_only_orphan_report_availability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            for report_available in (False, True):
                report = repository / "graphify-out" / "GRAPH_REPORT.md"
                report.parent.mkdir(parents=True, exist_ok=True)
                if report_available:
                    report.write_text("# Report\n", encoding="utf-8")
                elif report.exists():
                    report.unlink()
                metadata, nodes, edges = project_graphify(
                    repository,
                    "a" * 40,
                    "b" * 64,
                    {},
                )
                self.assertEqual(set(metadata), graphify_module.GRAPHIFY_ABSENT_METADATA_KEYS)
                self.assertIs(metadata["report_available"], report_available)
                self.assertEqual(metadata["unresolved_reasons"], [graphify_module.GRAPHIFY_ABSENT_REASON])
                self.assertEqual((nodes, edges), ([], []))

    def test_graphify_filesystem_failures_are_fixed_and_do_not_chain_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            marker = "C:\\Users\\foreign-owner\\Desktop\\checkout"
            with mock.patch.object(Path, "lstat", side_effect=OSError(marker)):
                with self.assertRaisesRegex(GraphifyFailure, "metadata read failed") as caught:
                    project_graphify(repository, "a" * 40, "b" * 64, {})
            self.assertNotIn(marker, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)

    def test_unknown_file_classification_fails_and_schemas_are_valid_json(self) -> None:
        for schema in sorted((MASTER_REFERENCE / "schema").glob("*.schema.json")):
            value = json.loads(schema.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
        records_schema = json.loads(
            (MASTER_REFERENCE / "schema" / "atlas-records.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("claimRecord", records_schema["$defs"])
        self.assertIn("lineRecord", records_schema["$defs"])
        self.assertIn("structuralEntityRecord", records_schema["$defs"])
        self.assertEqual(records_schema["properties"]["schema_version"]["const"], "1.1.0")
        self.assertEqual(records_schema["properties"]["record_count"]["minimum"], 1)
        self.assertEqual(records_schema["properties"]["records"]["minItems"], 1)
        graphify_schema = json.loads(
            (MASTER_REFERENCE / "schema" / "graphify-metadata.schema.json").read_text(encoding="utf-8")
        )
        available_contract = graphify_schema["allOf"][1]["then"]["required"]
        self.assertIn("excluded_node_dispositions", available_contract)
        self.assertIn("excluded_edge_dispositions", available_contract)
        self.assertFalse(graphify_schema["$defs"]["excludedNodeDisposition"]["additionalProperties"])
        self.assertFalse(graphify_schema["$defs"]["excludedEdgeDisposition"]["additionalProperties"])
        self.assertEqual(
            set(graphify_schema["$defs"]["excludedNodeDisposition"]["required"]),
            {"id", "disposition", "raw_index", "reason"},
        )
        self.assertEqual(
            set(graphify_schema["$defs"]["endpoint"]["required"]),
            {"state", "record_id", "anonymous_slot"},
        )
        for legacy_commitment in ("raw_record_digest", "opaque_record_hash", "opaque_identifier_hash"):
            self.assertNotIn(
                legacy_commitment,
                json.dumps(graphify_schema["$defs"], sort_keys=True),
            )
        manifest_schema = json.loads((MASTER_REFERENCE / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest_schema["$defs"]["chunkReceipt"]["properties"]["record_count"]["minimum"], 1)
        empty_group_contract = manifest_schema["$defs"]["groupReceipt"]["allOf"][0]
        self.assertEqual(empty_group_contract["then"]["properties"]["chunk_count"]["const"], 0)
        self.assertEqual(empty_group_contract["then"]["properties"]["chunks"]["maxItems"], 0)
        self.assertEqual(empty_group_contract["else"]["properties"]["chunk_count"]["minimum"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, {"mystery.unknown": "opaque\n"})
            output = base / "failed"
            with self.assertRaises(CompilationError):
                compile_repository(repository, output)
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["census"]["tracked_files"], 1)
            self.assertEqual(ledger["census"]["classified_files"], 0)
            self.assertTrue(any("extension" in error or "unclassified" in error for error in ledger["fatal_errors"]))

    def test_cloudflare_headers_contract_has_an_explicit_safe_text_classification(self) -> None:
        classification = classify_file("master-reference/public/_headers", "100644")
        self.assertEqual(classification["classification_errors"], [])
        self.assertEqual(classification["privacy_exposure"], "full")
        self.assertEqual(classification["language"], "config")
        self.assertEqual(classification["media_type"], "text/plain")
        self.assertEqual(classification["roles"], ["structured_data"])

        unexpected = classify_file("docs/_headers", "100644")
        self.assertEqual(unexpected["classification_errors"], ["extension_not_allowlisted:<none>"])

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(
                repository,
                {
                    "master-reference/public/_headers": (
                        "/atlas-projection/*.mjs.gz\n  ! Content-Encoding\n  Content-Type: application/gzip\n"
                    )
                },
            )
            output = base / "output"
            compile_repository(repository, output)

            file_record = group_records(output, "files")[0]
            self.assertEqual(file_record["path"], "master-reference/public/_headers")
            self.assertEqual(file_record["privacy_exposure"], "full")
            self.assertEqual(file_record["language"], "config")
            self.assertEqual(file_record["media_type"], "text/plain")
            self.assertEqual(file_record["roles"], ["structured_data"])

            structural_root = group_records(output, "structural_entities")[0]
            self.assertEqual(structural_root["path"], file_record["path"])
            self.assertEqual(structural_root["kind"], "configuration_document")
            line_records = group_records(output, "lines")
            self.assertEqual(len(line_records), 3)
            self.assertTrue(all(row["syntax_kind"] == "config_directive" for row in line_records))
            self.assertTrue(all(row["semantic_entity"] == structural_root["id"] for row in line_records))
            directives = group_records(output, "structured")
            self.assertEqual(len(directives), 3)
            self.assertTrue(all(row["value_type"] == "configuration_directive" for row in directives))
            ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["parsing"]["expected_nonblank_lines"], 3)
            self.assertEqual(ledger["parsing"]["line_records"], 3)


if __name__ == "__main__":
    unittest.main()
