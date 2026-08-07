from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from compiler import CompilationError, compile_repository  # noqa: E402
from compiler import compiler as compiler_module  # noqa: E402
from compiler import graphify as graphify_module  # noqa: E402
from compiler.graphify import GraphifyFailure, project_graphify  # noqa: E402
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
                row
                for row in lines
                if row["path"] == "sample.py" and row["syntax_kind"] == "unresolved_text"
            )
            structural_roots = {
                row["path"]: row for row in group_records(first_output, "structural_entities")
            }
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
            self.assertTrue(all(row["generation_provenance"]["state"] == "not_declared" for row in structural_roots.values()))
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
                row for row in group_records(first_output, "dependencies")
                if row["name"] == "example-package"
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

            ledger = json.loads((first_output / "completeness.json").read_text(encoding="utf-8"))
            architecture = json.loads(
                (first_output / "architecture-conformance.json").read_text(encoding="utf-8")
            )
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
                next(
                    item
                    for item in ledger["invariants"]
                    if item["name"] == "every_safe_line_structurally_mapped"
                )["passed"]
            )
            self.assertTrue(
                next(
                    item
                    for item in ledger["acceptance_gates"]
                    if item["name"] == "exact_clean_commit_binding"
                )["passed"]
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
                gate = next(
                    item for item in ledger["acceptance_gates"] if item["name"] == gate_name
                )
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
            rebuilt = "".join(
                str(line["text"]) + str(line["terminator"])
                for line in source["lines"]
            ).encode("utf-8")
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

            metadata = json.loads(
                (output / "graphify-metadata.json").read_text(encoding="utf-8")
            )
            self.assertFalse(metadata["available"])
            self.assertEqual(metadata["status"], "absent")
            self.assertEqual(metadata["schema_version"], "1.1.0")
            self.assertEqual(metadata["source_commit"], commit)
            self.assertEqual(
                metadata["source_tree_digest"], manifest["source_tree_digest"]
            )
            ledger = json.loads(
                (output / "completeness.json").read_text(encoding="utf-8")
            )
            gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "graphify_receipt_exact_source_bound"
            )
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
            self.assertEqual(metadata["node_disposition_counts"], {
                "retained": 2,
                "excluded_unsafe_source": 1,
                "excluded_untracked_or_private": 2,
            })
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
            self.assertEqual(len({item["opaque_record_hash"] for item in node_dispositions}), 3)
            self.assertEqual(len({item["id"] for item in edge_dispositions}), 2)
            self.assertEqual(len({item["opaque_record_hash"] for item in edge_dispositions}), 2)
            private_disposition = next(item for item in node_dispositions if item["raw_index"] == 1)
            hidden_edge = next(item for item in edge_dispositions if item["raw_index"] == 1)
            self.assertEqual(hidden_edge["target_endpoint"]["record_id"], private_disposition["id"])
            self.assertEqual(
                hidden_edge["target_endpoint"]["opaque_identifier_hash"],
                private_disposition["opaque_identifier_hash"],
            )
            missing_edge = next(item for item in edge_dispositions if item["raw_index"] == 2)
            self.assertEqual(missing_edge["target_endpoint"]["state"], "missing_node")
            self.assertIsNone(missing_edge["target_endpoint"]["record_id"])
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
            self.assertEqual(metadata["community_status_counts"], {
                "projected_complete": 1,
                "projected_partial": 1,
                "excluded": 2,
            })
            disposition = {
                item["community"]: item for item in metadata["community_dispositions"]
            }
            self.assertEqual(disposition[4]["retained_nodes"], 1)
            self.assertEqual(disposition[4]["excluded_nodes"], 1)

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
                "opaque_record_hash": "b" * 64,
                "opaque_identifier_hash": "c" * 64,
                "raw_record_digest": "d" * 64,
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

            ledger = json.loads(
                (output / "completeness.json").read_text(encoding="utf-8")
            )
            gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "graphify_receipt_exact_source_bound"
            )
            self.assertFalse(gate["passed"])
            self.assertEqual((gate["expected"], gate["actual"]), (1, 0))
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
                    "master-reference/sample.jsonc": "{\n  // structural only\n  \"theme\": \"dark\"\n}\n",
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
            self.assertTrue({"LIMIT", "alpha", "beta", "Widget"}.issubset(
                {row["name"] for row in symbols if row["entity_type"] == "typescript_constant"}
            ))
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
                item
                for item in ledger["invariants"]
                if item["name"] == "every_published_record_has_entity_type"
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
                next(
                    item
                    for item in ledger["acceptance_gates"]
                    if item["name"] == "exact_clean_commit_binding"
                )["passed"]
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
            gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "every_safe_line_structurally_mapped"
            )
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
            gate = next(
                item
                for item in ledger["invariants"]
                if item["name"] == "every_safe_line_structurally_mapped"
            )
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
                item
                for item in ledger["invariants"]
                if item["name"] == "every_safe_line_structurally_mapped"
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
                        '  return <button aria-label={label} onClick={() => undefined}>{label}</button>;\n'
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
        graphify_schema = json.loads(
            (MASTER_REFERENCE / "schema" / "graphify-metadata.schema.json").read_text(encoding="utf-8")
        )
        available_contract = graphify_schema["allOf"][1]["then"]["required"]
        self.assertIn("excluded_node_dispositions", available_contract)
        self.assertIn("excluded_edge_dispositions", available_contract)
        self.assertFalse(
            graphify_schema["$defs"]["excludedNodeDisposition"]["additionalProperties"]
        )
        self.assertFalse(
            graphify_schema["$defs"]["excludedEdgeDisposition"]["additionalProperties"]
        )

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


if __name__ == "__main__":
    unittest.main()
