"""Census depth: one declared owner, identity-only records, never skipped privacy.

``compiler.policy.CENSUS_DEPTH_DECLARATIONS`` is the only place a path prefix
can be censused below full depth.  These tests bound that declaration to its
reviewed receipt (a named BLOCK category, like the repository's other external
BLOCK categories), prove the compiler follows it and nothing else, prove an
identity-depth file still passes through the complete privacy decision, and
prove every downstream validator refuses a depth that differs from the owner.
"""

from __future__ import annotations

import json
import os
import re
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
from compiler import policy as policy_module  # noqa: E402
from compiler.model import canonical_json  # noqa: E402
from compiler.schema_validation import (  # noqa: E402
    CensusDepthValidationError,
    SchemaValidationError,
    validate_census_depth_receipt,
    validate_compiler_output,
)


CENSUS_DEPTH_BLOCK_CODE = "census_depth_identity_line_projection_deferred"
# The reviewed receipt for every declared identity-depth prefix.  Adding,
# removing or changing a declaration without reviewing it here fails with the
# BLOCK code above, exactly like the repository's other bounded BLOCK sets.
REVIEWED_CENSUS_DEPTH_DECLARATIONS = {
    "atlas-scope/": {
        "census_depth": "identity",
        "reason": "line_projection_deferred:size_ceiling",
        "block_category": CENSUS_DEPTH_BLOCK_CODE,
        "follow_up_owner": "master-reference/compiler: compact per-line record encoding",
    }
}
DEFERRED_GROUPS = (
    "calls",
    "components",
    "configs",
    "datasets",
    "dependencies",
    "documents",
    "lines",
    "manifests",
    "markdown",
    "routes",
    "source_text",
    "structural_entities",
    "structured",
    "symbols",
    "tests",
    "workflows",
)
APP_SOURCE = 'import { helper } from "./util";\n\nexport const value = helper(1);\n'
UTIL_SOURCE = "export function helper(input: number): number {\n  return input + 1;\n}\n"


def _git(root: Path, *arguments: str) -> str:
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


def initialize_repository(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "fixture")


def group_records(output: Path, group: str) -> list[dict[str, object]]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    for receipt in manifest["groups"][group]["chunks"]:
        records.extend(json.loads((output / receipt["path"]).read_text(encoding="utf-8"))["records"])
    return records


def architecture_contract() -> str:
    return json.dumps(
        {
            "schema_version": "2.0.0",
            "python_import_roots": [],
            "internal_module_prefixes": [],
            "components": [
                {"id": "scope", "paths": ["atlas-scope/"]},
                {"id": "repository", "paths": ["README.md", "docs/", "master-reference/", "tools/"]},
            ],
            "exclusions": [],
            "allowed_edges": [],
            "forbidden_edges": [],
            "runtime_phases": [{"id": "compile", "order": 1, "required": False}],
            "synthetic_runtime_traces": [
                {
                    "id": "fixture",
                    "events": [{"phase": "compile", "status": "passed", "receipt_id": "synthetic:fixture:compile"}],
                }
            ],
        },
        indent=2,
        sort_keys=True,
    )


def fixture_files() -> dict[str, str]:
    return {
        "README.md": "# Fixture\n",
        "docs/atlas-scope/notes.md": "# Not under the declared prefix\n\nFull depth.\n",
        "tools/app.ts": APP_SOURCE,
        "tools/util.ts": UTIL_SOURCE,
        "atlas-scope/src/app.ts": APP_SOURCE,
        "atlas-scope/src/util.ts": UTIL_SOURCE,
        "atlas-scope/README.md": "# Atlas Scope\n\nIdentity-only fixture.\n",
        "atlas-scope/package.json": '{\n  "name": "fixture",\n  "dependencies": {"left-pad": "1.0.0"}\n}\n',
        "atlas-scope/tsconfig.json": '{\n  // comment\n  "compilerOptions": {"strict": true}\n}\n',
        "master-reference/governance/architecture.json": architecture_contract() + "\n",
    }


def synthetic_access_key() -> str:
    # Assembled at run time so this tracked test source never matches the rule.
    return "AK" + "IA" + "Q" * 16


class CensusDepthDeclarationTests(unittest.TestCase):
    def test_declarations_are_exactly_the_reviewed_receipt(self) -> None:
        observed = {
            row["prefix"]: {key: row[key] for key in ("census_depth", "reason", "block_category", "follow_up_owner")}
            for row in policy_module.census_depth_declaration_receipts()
        }
        if observed != REVIEWED_CENSUS_DEPTH_DECLARATIONS:
            self.fail(
                f"{CENSUS_DEPTH_BLOCK_CODE}: census-depth declarations changed; review the deferral, its BLOCK "
                f"category and follow-up owner, then reconcile this receipt (observed prefixes: {sorted(observed)})"
            )
        self.assertEqual(policy_module.validate_census_depth_declarations(), [])

    def test_a_declaration_without_its_receipt_fields_is_refused(self) -> None:
        declaration = policy_module.CensusDepthDeclaration
        good = policy_module.CENSUS_DEPTH_DECLARATIONS[0]
        cases = {
            "census_depth_block_category_invalid:tools/": declaration(
                "tools/", "identity", good.reason, "", good.follow_up_owner
            ),
            "census_depth_reason_invalid:tools/": declaration(
                "tools/", "identity", "", good.block_category, good.follow_up_owner
            ),
            "census_depth_follow_up_owner_missing:tools/": declaration(
                "tools/", "identity", good.reason, good.block_category, " "
            ),
            "census_depth_value_invalid:tools/": declaration(
                "tools/", "full", good.reason, good.block_category, good.follow_up_owner
            ),
            "census_depth_prefix_invalid:../escape/": declaration(
                "../escape/", "identity", good.reason, good.block_category, good.follow_up_owner
            ),
            "census_depth_prefix_invalid:not-allowlisted/": declaration(
                "not-allowlisted/", "identity", good.reason, good.block_category, good.follow_up_owner
            ),
        }
        for code, row in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, policy_module.validate_census_depth_declarations((good, row)))
        nested = declaration("atlas-scope/src/", "identity", good.reason, good.block_category, good.follow_up_owner)
        self.assertIn(
            "census_depth_prefix_overlaps:atlas-scope/src/",
            policy_module.validate_census_depth_declarations((good, nested)),
        )

    def test_the_decision_is_a_prefix_rule_owned_by_policy(self) -> None:
        self.assertEqual(
            policy_module.census_depth_decision("atlas-scope/src/app.ts"),
            ("identity", "line_projection_deferred:size_ceiling"),
        )
        for path in ("atlas-scope-other/x.ts", "docs/atlas-scope/notes.md", "tools/atlas-scope.ts", "README.md"):
            with self.subTest(path=path):
                self.assertEqual(policy_module.census_depth_decision(path), ("full", None))

    def test_no_other_source_owns_the_deferral_literals(self) -> None:
        # The reason and BLOCK category are data owned by policy.py; every other
        # producer or consumer must read them from the policy or the ledger.
        literals = {
            "line_projection_deferred",
            CENSUS_DEPTH_BLOCK_CODE,
        }
        suffixes = {".py", ".mjs", ".js", ".ts", ".tsx", ".json"}
        skipped = {"node_modules", "tests", "dist", "public", ".vinext", ".wrangler"}
        offenders: list[str] = []
        for directory, subdirectories, names in os.walk(MASTER_REFERENCE):
            subdirectories[:] = sorted(name for name in subdirectories if name not in skipped)
            for name in sorted(names):
                path = Path(directory) / name
                relative = path.relative_to(MASTER_REFERENCE).as_posix()
                if path.suffix not in suffixes or relative == "compiler/policy.py":
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(literal in text for literal in literals):
                    offenders.append(relative)
        self.assertEqual(offenders, [], "only compiler/policy.py may own census-depth deferral literals")


class CensusDepthCompilerTests(unittest.TestCase):
    def _compile(self, files: dict[str, str]) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
        temporary = tempfile.TemporaryDirectory()
        base = Path(temporary.name)
        repository = base / "repo"
        initialize_repository(repository, files)
        output = base / "output"
        compile_repository(repository, output)
        return repository, output, temporary

    def test_identity_prefix_emits_only_identity_records_and_an_explicit_receipt(self) -> None:
        _repository, output, temporary = self._compile(fixture_files())
        self.addCleanup(temporary.cleanup)
        validate_compiler_output(output)
        files = {str(row["path"]): row for row in group_records(output, "files")}
        identity_paths = {path for path in files if path.startswith("atlas-scope/")}
        self.assertEqual(len(identity_paths), 5)
        for path in sorted(files):
            row = files[path]
            with self.subTest(path=path):
                if path in identity_paths:
                    self.assertEqual(row["census_depth"], "identity")
                    self.assertEqual(row["census_depth_reason"], "line_projection_deferred:size_ceiling")
                    self.assertEqual(row["parse_status"], "identity_census")
                    self.assertEqual(row["privacy_exposure"], "full")
                    self.assertRegex(str(row["content_digest"]), r"^[0-9a-f]{64}$")
                    self.assertRegex(str(row["git_blob_oid"]), r"^[0-9a-f]{40}$")
                    self.assertGreater(int(row["size_bytes"]), 0)
                    self.assertGreater(int(row["nonblank_line_count"]), 0)
                    self.assertEqual(row["unresolved_reasons"], ["line_projection_deferred:size_ceiling"])
                else:
                    self.assertEqual(row["census_depth"], "full")
                    self.assertIsNone(row["census_depth_reason"])
                    self.assertEqual(row["parse_status"], "parsed")
        for group in DEFERRED_GROUPS:
            with self.subTest(group=group):
                self.assertFalse(
                    [row for row in group_records(output, group) if str(row.get("path")) in identity_paths],
                    f"{group} carries a record for an identity-depth file",
                )
        imports = [row for row in group_records(output, "imports") if row["path"] == "atlas-scope/src/app.ts"]
        self.assertEqual([row["module"] for row in imports], ["./util"])
        self.assertTrue(any(row["path"] == "tools/app.ts" for row in group_records(output, "source_text")))

        ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
        receipt = ledger["census_depth"]
        self.assertEqual(receipt["status"], "identity_depth_deferred")
        self.assertEqual(receipt["identity_depth_files"], 5)
        self.assertEqual(receipt["full_depth_files"], len(files) - 5)
        self.assertEqual(receipt["block_categories"], [CENSUS_DEPTH_BLOCK_CODE])
        declaration = receipt["declarations"][0]
        self.assertEqual(declaration["prefix"], "atlas-scope/")
        self.assertEqual(declaration["tracked_files"], 5)
        self.assertEqual(declaration["text_files"], 5)
        self.assertEqual(declaration["privacy_scanned_text_files"], 5)
        self.assertEqual(declaration["retained_import_records"], 1)
        self.assertEqual(
            declaration["deferred_nonblank_lines"],
            sum(int(files[path]["nonblank_line_count"]) for path in identity_paths),
        )
        self.assertEqual(receipt["identity_depth_nonblank_lines_deferred"], declaration["deferred_nonblank_lines"])
        invariants = {row["name"]: row for row in ledger["invariants"]}
        self.assertTrue(invariants["every_identity_depth_file_declared_privacy_scanned_and_unprojected"]["passed"])
        self.assertTrue(invariants["every_nonblank_text_line_has_one_record"]["passed"])
        self.assertEqual(
            invariants["every_nonblank_text_line_has_one_record"]["expected"],
            sum(int(row["nonblank_line_count"]) for path, row in files.items() if path not in identity_paths),
        )
        gates = {row["name"]: row for row in ledger["acceptance_gates"]}
        gate = gates["every_tracked_text_file_line_censused"]
        self.assertFalse(gate["passed"])
        self.assertEqual((gate["expected"], gate["actual"]), (len(files), len(files) - 5))
        scan = ledger["privacy"]["forbidden_content_scan"]
        self.assertEqual(scan["eligible_text_files"], len(files))
        self.assertEqual(scan["scanned_text_files"], len(files))
        line_claim = next(
            row for row in group_records(output, "claims") if row["predicate"] == "repository.nonblank_line_record_count"
        )
        self.assertIn(CENSUS_DEPTH_BLOCK_CODE, line_claim["unresolved_reasons"])
        # The count is exact over the full-depth census only; the claim's
        # denominator says so instead of standing over every tracked path.
        self.assertEqual(line_claim["denominator"]["value"], len(files) - 5)
        self.assertEqual(line_claim["denominator"]["unit"], "full_depth_git_tracked_paths")
        self.assertIn("identity_depth_files_excluded", line_claim["denominator"]["basis"])
        # Every gate whose denominator is drawn from a record group an
        # identity-depth file never emits states that scope; the others do not.
        deferred = set(DEFERRED_GROUPS)
        scoped = set()
        for row in [*ledger["invariants"], *ledger["acceptance_gates"]]:
            groups = set(compiler_module.GATE_DENOMINATOR_GROUPS[row["name"]])
            with self.subTest(gate=row["name"]):
                if groups & deferred:
                    self.assertEqual(row["denominator_scope"], "full_depth_census_identity_depth_files_excluded")
                    scoped.add(row["name"])
                else:
                    self.assertNotIn("denominator_scope", row)
        self.assertTrue(
            {
                "every_symbol_has_dossier_fields",
                "every_gui_surface_has_standardized_evidence_honest_dossier",
                "every_safe_line_behaviorally_explained",
                "every_nonblank_text_line_has_one_record",
            }
            <= scoped
        )

        architecture = json.loads((output / "architecture-conformance.json").read_text(encoding="utf-8"))
        self.assertEqual(architecture["status"], "passed")
        self.assertEqual(
            architecture["unexamined_static_edges"],
            [
                {
                    "edge_kind": "import_bound_static_call_candidate",
                    "state": "unexamined",
                    "reason": "line_projection_deferred:size_ceiling",
                    "source_file_count": 5,
                    "source_components": ["scope"],
                }
            ],
        )
        self.assertTrue(
            any(
                edge["source_path"] == "atlas-scope/src/app.ts" and edge["target_path"] == "atlas-scope/src/util.ts"
                for edge in architecture["static_edges"]
            )
        )

    def test_full_depth_repository_reports_no_deferral(self) -> None:
        files = {path: text for path, text in fixture_files().items() if not path.startswith("atlas-scope/")}
        _repository, output, temporary = self._compile(files)
        self.addCleanup(temporary.cleanup)
        validate_compiler_output(output)
        ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["census_depth"]["status"], "full_depth")
        self.assertEqual(ledger["census_depth"]["block_categories"], [])
        self.assertEqual(ledger["census_depth"]["declarations"][0]["tracked_files"], 0)
        gate = next(row for row in ledger["acceptance_gates"] if row["name"] == "every_tracked_text_file_line_censused")
        self.assertTrue(gate["passed"])
        # With nothing deferred, no denominator is qualified.
        for row in [*ledger["invariants"], *ledger["acceptance_gates"]]:
            with self.subTest(gate=row["name"]):
                self.assertNotIn("denominator_scope", row)
        architecture = json.loads((output / "architecture-conformance.json").read_text(encoding="utf-8"))
        self.assertEqual(architecture["unexamined_static_edges"], [])

    def test_only_the_declaration_defers_census_depth(self) -> None:
        with mock.patch.object(policy_module, "CENSUS_DEPTH_DECLARATIONS", ()):
            _repository, output, temporary = self._compile(fixture_files())
            self.addCleanup(temporary.cleanup)
            validate_compiler_output(output)
            files = group_records(output, "files")
            self.assertEqual({row["census_depth"] for row in files}, {"full"})
            source_paths = {row["path"] for row in group_records(output, "source_text")}
            self.assertEqual(source_paths, {row["path"] for row in files})

        moved = policy_module.CensusDepthDeclaration(
            prefix="tools/",
            census_depth="identity",
            reason="line_projection_deferred:size_ceiling",
            block_category=CENSUS_DEPTH_BLOCK_CODE,
            follow_up_owner="fixture",
        )
        with mock.patch.object(policy_module, "CENSUS_DEPTH_DECLARATIONS", (moved,)):
            _repository, output, temporary = self._compile(fixture_files())
            self.addCleanup(temporary.cleanup)
            validate_compiler_output(output)
            depths = {row["path"]: row["census_depth"] for row in group_records(output, "files")}
            self.assertEqual({path for path, depth in depths.items() if depth == "identity"}, {"tools/app.ts", "tools/util.ts"})

    def test_identity_depth_file_is_privacy_scanned_exactly_like_a_full_depth_file(self) -> None:
        planted = f"export const leaked = \"{synthetic_access_key()}\";\n"
        outcomes: dict[str, tuple[tuple[str, ...], dict[str, object]]] = {}
        for label, path in (("full", "tools/leak.ts"), ("identity", "atlas-scope/src/leak.ts")):
            with self.subTest(depth=label), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                repository = base / "repo"
                initialize_repository(repository, {**fixture_files(), path: planted})
                output = base / "output"
                scanned: list[str] = []
                real_scanner = compiler_module.forbidden_content_findings

                def recording_scanner(candidate: str, text: str) -> list[dict[str, object]]:
                    scanned.append(candidate)
                    return real_scanner(candidate, text)

                with (
                    mock.patch.object(compiler_module, "forbidden_content_findings", side_effect=recording_scanner),
                    self.assertRaises(CompilationError) as caught,
                ):
                    compile_repository(repository, output)
                self.assertIn(path, scanned)
                self.assertFalse((output / "manifest.json").exists())
                ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
                self.assertNotIn(synthetic_access_key(), (output / "completeness.json").read_text(encoding="utf-8"))
                outcomes[label] = (caught.exception.errors, ledger["privacy"]["forbidden_content_scan"])
        normalized = {
            label: (
                tuple(error.replace("atlas-scope/src/leak.ts", "<leak>").replace("tools/leak.ts", "<leak>") for error in errors),
                json.loads(
                    canonical_json(scan)
                    .decode("utf-8")
                    .replace("atlas-scope/src/leak.ts", "<leak>")
                    .replace("tools/leak.ts", "<leak>")
                ),
            )
            for label, (errors, scan) in outcomes.items()
        }
        self.assertEqual(normalized["identity"], normalized["full"])
        self.assertEqual(normalized["identity"][1]["status"], "failed")
        self.assertIn("<leak>:1: forbidden-content rule aws_access_key", normalized["identity"][0])

    def test_validators_refuse_a_depth_that_differs_from_the_policy_owner(self) -> None:
        _repository, output, temporary = self._compile(fixture_files())
        self.addCleanup(temporary.cleanup)
        ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
        files = group_records(output, "files")
        validate_census_depth_receipt(ledger, files)

        def mutated(path: str, **changes: object) -> list[dict[str, object]]:
            return [{**row, **changes} if row["path"] == path else row for row in files]

        cases = {
            "full file presented as deferred": mutated(
                "tools/app.ts", census_depth="identity", census_depth_reason="line_projection_deferred:size_ceiling"
            ),
            "deferred file presented as line-covered": mutated(
                "atlas-scope/src/app.ts", census_depth="full", census_depth_reason=None, parse_status="parsed"
            ),
            "deferred file with another reason": mutated(
                "atlas-scope/src/app.ts", census_depth_reason="other_reason:fixture"
            ),
        }
        for label, candidate in cases.items():
            with self.subTest(case=label), self.assertRaises(CensusDepthValidationError):
                validate_census_depth_receipt(ledger, candidate)
        for label, change in {
            "hidden block category": {"block_categories": []},
            "shrunk deferral count": {"identity_depth_files": 4},
            "rewritten reason": {
                "declarations": [{**ledger["census_depth"]["declarations"][0], "reason": "other_reason:fixture"}]
            },
        }.items():
            with self.subTest(case=label), self.assertRaises(CensusDepthValidationError):
                validate_census_depth_receipt({**ledger, "census_depth": {**ledger["census_depth"], **change}}, files)

        chunk = output / "chunks" / "files" / "00000.json"
        envelope = json.loads(chunk.read_text(encoding="utf-8"))
        for row in envelope["records"]:
            if row["path"] == "atlas-scope/src/app.ts":
                row["census_depth"] = "full"
                row["census_depth_reason"] = None
        chunk.write_bytes(canonical_json(envelope))
        with self.assertRaises(SchemaValidationError):
            validate_compiler_output(output)

    def test_census_depth_invariant_fails_when_a_deferred_group_leaks(self) -> None:
        original = compiler_module._accept_identity_parse_result

        def leaking(records, file_record, result, text):  # type: ignore[no-untyped-def]
            original(records, file_record, result, text)
            records["symbols"].extend(result.symbols)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            initialize_repository(repository, fixture_files())
            with (
                mock.patch.object(compiler_module, "_accept_identity_parse_result", side_effect=leaking),
                self.assertRaises(CompilationError),
            ):
                compile_repository(repository, base / "output")
            ledger = json.loads((base / "output" / "completeness.json").read_text(encoding="utf-8"))
            invariant = next(
                row
                for row in ledger["invariants"]
                if row["name"] == "every_identity_depth_file_declared_privacy_scanned_and_unprojected"
            )
            self.assertFalse(invariant["passed"])


class CensusDepthSchemaTests(unittest.TestCase):
    def test_every_ledger_gate_must_declare_its_denominator_groups(self) -> None:
        gates = [{"name": "an_undeclared_gate", "passed": True, "expected": 1, "actual": 1}]
        with self.assertRaisesRegex(RuntimeError, "an_undeclared_gate"):
            compiler_module._scope_gate_denominators(gates, identity_depth_files=0)
        self.assertTrue(
            set(compiler_module.GATE_DENOMINATOR_GROUPS.values()) and all(
                set(groups) <= set(compiler_module.RECORD_GROUPS)
                for groups in compiler_module.GATE_DENOMINATOR_GROUPS.values()
            )
        )

    def test_file_record_schema_binds_depth_reason_and_parse_status(self) -> None:
        schema = json.loads((MASTER_REFERENCE / "schema" / "atlas-records.schema.json").read_text(encoding="utf-8"))
        fence = set(schema["$defs"]["filesRecordKeyFence"]["propertyNames"]["enum"])
        self.assertTrue({"census_depth", "census_depth_reason"} <= fence)
        ledger_schema = json.loads(
            (MASTER_REFERENCE / "schema" / "completeness-ledger.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("census_depth", ledger_schema["required"])
        text = json.dumps(ledger_schema)
        self.assertTrue(re.search(r"every_tracked_text_file_line_censused", text))


if __name__ == "__main__":
    unittest.main()
