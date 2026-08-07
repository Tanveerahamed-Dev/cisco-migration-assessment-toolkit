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


def initialize_repository(root: Path, files: dict[str, str | bytes]) -> str:
    root.mkdir(parents=True)
    git(root, "init", "-q")
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
                    "docs/decisions/0001-proposed.md": "# Decision\n\n**Status:** proposed\n",
                    "reference-data/sample.json": b'\xef\xbb\xbf{"items":[{"name":"one"}],"enabled":true}\r\n',
                    "requirements.txt": "example-package==1.2.3\n",
                    "sample.py": (
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
            self.assertEqual(first_manifest["groups"]["files"]["record_count"], 9)
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

            self.assertTrue(any(row["qualified_name"] == "helper" for row in group_records(first_output, "symbols")))
            helper = next(row for row in group_records(first_output, "symbols") if row["qualified_name"] == "helper")
            self.assertEqual(helper["stable_urn"], helper["id"])
            self.assertEqual(helper["explanation_depth"], 1)
            self.assertEqual(helper["review_state"], "not_human_reviewed")
            self.assertIn("runtime_trace_not_collected", helper["limitations"])
            self.assertTrue(any(row["name"] == "Dashboard" for row in group_records(first_output, "components")))
            self.assertTrue(any(row["route"] == "/health" for row in group_records(first_output, "routes")))
            self.assertTrue(any(row["route"] == "/dashboard" for row in group_records(first_output, "routes")))
            self.assertTrue(any(row["name"] == "dashboard" for row in group_records(first_output, "tests")))
            self.assertTrue(
                any(row["name"] == "example-package" for row in group_records(first_output, "dependencies"))
            )

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
            self.assertTrue(
                next(
                    item
                    for item in ledger["acceptance_gates"]
                    if item["name"] == "exact_clean_commit_binding"
                )["passed"]
            )
            self.assertEqual(architecture, ledger["architecture_conformance"])
            self.assertEqual(architecture["status"], "not_declared")
            self.assertEqual(
                manifest["architecture_conformance"]["sha256"],
                hashlib.sha256((first_output / "architecture-conformance.json").read_bytes()).hexdigest(),
            )

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
            self.assertTrue(all(row["status"] == "candidate" for row in claims))
            self.assertTrue(all(row["verdict"] == "indeterminate" for row in claims))
            self.assertTrue(all(row["freshness"] == "unknown" for row in claims))
            self.assertTrue(all(not row["current_view"] for row in claims))
            self.assertTrue(all("dirty_worktree_not_exact_commit_bound" in row["unresolved_reasons"] for row in claims))

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
            self.assertEqual(file_record["privacy_exposure"], "metadata_only")
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
