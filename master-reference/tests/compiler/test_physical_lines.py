"""Physical lines: one line definition shared by Git, the tokenizers, and the projection.

``str.splitlines`` also breaks on VT, FF, FS, GS, RS, NEL (U+0085), LS (U+2028) and
PS (U+2029).  A literal one of those inside a string literal or comment is a valid
source character that Git, the Python tokenizer (``ast`` ``lineno``), and the exact
``source_text`` projection all keep inside its line.  Every compiler line number and
line count must therefore come from the CRLF/LF/CR definition owned by
``compiler.parsers.physical_lines``; the TypeScript adapter must apply the same
definition instead of TypeScript's own line starts, which also break on LS/PS.

Regression: a literal U+2028 inside a string on line 722 of a 3,567-line Python test
module made ``compile_repository`` fail with ``KeyError: (path, 3568)`` -- the
``splitlines``-numbered line rows no longer joined the exactly-split ``source_text``
rows -- and every line after it was silently renumbered relative to the AST.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from compiler import compile_repository  # noqa: E402
from compiler import compiler as compiler_module  # noqa: E402
from compiler import parsers as parsers_module  # noqa: E402
from compiler.schema_validation import validate_compiler_output  # noqa: E402


# Every separator ``str.splitlines`` honours that CRLF/LF/CR splitting does not.
SPLITLINES_ONLY_SEPARATORS = ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " ")

PYTHON_FIXTURE_PATH = "webapp/backend/separators.py"
PYTHON_FIXTURE = (
    '"""Separators str.splitlines breaks on; Git and the tokenizer keep them in their line."""\n'
    "\n"
    'SEPARATORS = {"line-separator": " ", "paragraph-separator": " ", "next-line": "\x85"}\n'
    "\x0c\n"
    "\n"
    "def after_separators():\n"
    "    return SEPARATORS\n"
)
PYTHON_PHYSICAL_LINES = 7
PYTHON_NONBLANK_LINES = (1, 3, 6, 7)
PYTHON_SYMBOL_RANGE = (6, 7)

TYPESCRIPT_FIXTURE_PATH = "webapp/src/separators.ts"
TYPESCRIPT_FIXTURE = (
    'export const separators = [" ", " "];\n'
    "\n"
    "export function afterSeparators(): string[] {\n"
    "  return separators;\n"
    "}\n"
)
TYPESCRIPT_PHYSICAL_LINES = 5
TYPESCRIPT_NONBLANK_LINES = (1, 3, 4, 5)
TYPESCRIPT_SYMBOL_RANGE = (3, 5)


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


def _initialize_repository(root: Path, files: dict[str, str]) -> None:
    """Commit the fixture bytes exactly (no EOL conversion, no BOM)."""

    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", "fixture")


def _group_records(output: Path, group: str) -> list[dict[str, object]]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    for receipt in manifest["groups"][group]["chunks"]:
        envelope = json.loads((output / receipt["path"]).read_text(encoding="utf-8"))
        records.extend(envelope["records"])
    return records


class PhysicalLinesTests(unittest.TestCase):
    def test_physical_lines_break_only_on_crlf_lf_cr(self) -> None:
        inner = "".join(SPLITLINES_ONLY_SEPARATORS)
        text = f"a{inner}b\r\nc{inner}\rd\n\ne"
        self.assertGreater(len(text.splitlines()), 5, "the fixture must exercise every splitlines-only separator")

        lines = parsers_module.physical_lines(text)
        self.assertEqual(lines, [f"a{inner}b", f"c{inner}", "d", "", "e"])
        kept = parsers_module.physical_lines(text, keepends=True)
        self.assertEqual(kept, [f"a{inner}b\r\n", f"c{inner}\r", "d\n", "\n", "e"])
        self.assertEqual("".join(kept), text)

        # Edge shapes agree with str.splitlines wherever only CR/LF are involved.
        for sample in ("", "\n", "a", "a\n", "a\r\n", "a\r", "\r\n\r\n", "a\n\nb"):
            self.assertEqual(parsers_module.physical_lines(sample), sample.splitlines(), repr(sample))
            self.assertEqual(
                parsers_module.physical_lines(sample, keepends=True), sample.splitlines(keepends=True), repr(sample)
            )

    def test_exact_source_lines_share_the_physical_line_definition(self) -> None:
        inner = "".join(SPLITLINES_ONLY_SEPARATORS)
        text = f"a{inner}b\r\nc\rd\n\ne"
        exact = compiler_module._exact_source_lines(text)
        self.assertEqual([row["number"] for row in exact], [1, 2, 3, 4, 5])
        self.assertEqual([row["text"] for row in exact], parsers_module.physical_lines(text))
        self.assertEqual(
            [row["text"] + row["terminator"] for row in exact],
            parsers_module.physical_lines(text, keepends=True),
        )

    def test_python_source_with_splitlines_only_separators_compiles_to_exact_physical_lines(self) -> None:
        self.assertEqual(PYTHON_FIXTURE.count("\n"), PYTHON_PHYSICAL_LINES)
        self.assertGreater(len(PYTHON_FIXTURE.splitlines()), PYTHON_PHYSICAL_LINES)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            _initialize_repository(repository, {PYTHON_FIXTURE_PATH: PYTHON_FIXTURE})
            output = base / "compiled"

            compile_repository(repository, output)
            validate_compiler_output(output)

            self._assert_exact_physical_projection(
                output,
                path=PYTHON_FIXTURE_PATH,
                physical_lines=PYTHON_PHYSICAL_LINES,
                nonblank_lines=PYTHON_NONBLANK_LINES,
                symbol_name="after_separators",
                symbol_range=PYTHON_SYMBOL_RANGE,
                separator_line=3,
            )

    def test_typescript_source_with_line_and_paragraph_separators_compiles_to_exact_physical_lines(self) -> None:
        self.assertEqual(TYPESCRIPT_FIXTURE.count("\n"), TYPESCRIPT_PHYSICAL_LINES)
        self.assertGreater(len(TYPESCRIPT_FIXTURE.splitlines()), TYPESCRIPT_PHYSICAL_LINES)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            _initialize_repository(repository, {TYPESCRIPT_FIXTURE_PATH: TYPESCRIPT_FIXTURE})
            output = base / "compiled"

            compile_repository(repository, output)
            validate_compiler_output(output)

            self._assert_exact_physical_projection(
                output,
                path=TYPESCRIPT_FIXTURE_PATH,
                physical_lines=TYPESCRIPT_PHYSICAL_LINES,
                nonblank_lines=TYPESCRIPT_NONBLANK_LINES,
                symbol_name="afterSeparators",
                symbol_range=TYPESCRIPT_SYMBOL_RANGE,
                separator_line=1,
            )

    def test_an_unexpected_failure_names_its_exception_type(self) -> None:
        """The hosted log of this defect read only ``unexpected compiler failure: ('<path>', 3568)``: the bare
        str() of a KeyError, with its type dropped. The refusal must name the type so a CI log is diagnosable."""
        original = compiler_module._enrich_semantic_records

        def explode(*_arguments: object, **_keywords: object) -> None:
            raise KeyError(("webapp/x.py", 3))

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repo"
            _initialize_repository(repository, {PYTHON_FIXTURE_PATH: PYTHON_FIXTURE})
            compiler_module._enrich_semantic_records = explode
            try:
                with self.assertRaises(compiler_module.CompilationError) as raised:
                    compile_repository(repository, base / "compiled")
            finally:
                compiler_module._enrich_semantic_records = original
        self.assertIn("unexpected compiler failure: KeyError: ('webapp/x.py', 3)", raised.exception.errors)

    def _assert_exact_physical_projection(
        self,
        output: Path,
        *,
        path: str,
        physical_lines: int,
        nonblank_lines: tuple[int, ...],
        symbol_name: str,
        symbol_range: tuple[int, int],
        separator_line: int,
    ) -> None:
        file_record = next(row for row in _group_records(output, "files") if row["path"] == path)
        self.assertEqual(file_record["census_depth"], "full", "the fixture path must be censused at full depth")
        self.assertEqual(file_record["parse_status"], "parsed")
        self.assertEqual(file_record["line_count"], physical_lines)
        self.assertEqual(file_record["nonblank_line_count"], len(nonblank_lines))

        source = next(row for row in _group_records(output, "source_text") if row["path"] == path)
        self.assertEqual(source["line_count"], physical_lines)
        self.assertEqual([row["number"] for row in source["lines"]], list(range(1, physical_lines + 1)))
        self.assertTrue(
            any(separator in str(source["lines"][separator_line - 1]["text"]) for separator in (" ", " ")),
            "the separator must stay inside its physical line",
        )
        digests = {int(row["number"]): row["line_digest"] for row in source["lines"]}

        lines = sorted(
            (row for row in _group_records(output, "lines") if row["path"] == path),
            key=lambda row: int(row["line"]),
        )
        self.assertEqual([row["line"] for row in lines], list(nonblank_lines))
        for row in lines:
            self.assertEqual(row["line_digest"], digests[int(row["line"])], row["line"])
            self.assertNotEqual(row["syntax_kind"], "unresolved_text", row["line"])
            self.assertEqual(row["explanation_depth"], 1, row["line"])

        symbol = next(
            row
            for row in _group_records(output, "symbols")
            if row["path"] == path and row["name"] == symbol_name
        )
        self.assertEqual((symbol["range"]["start_line"], symbol["range"]["end_line"]), symbol_range)
        start, end = symbol_range
        for row in lines:
            if start <= int(row["line"]) <= end:
                self.assertEqual(row["semantic_entity"], symbol["id"], row["line"])
                self.assertEqual(row["structural_mapping_basis"], "symbol_range", row["line"])
            else:
                self.assertNotEqual(row["semantic_entity"], symbol["id"], row["line"])

        root = next(
            row
            for row in _group_records(output, "structural_entities")
            if row["path"] == path and row.get("root_scope") == "parsed_source"
        )
        self.assertEqual(root["line_count"], physical_lines)
        self.assertEqual(root["range"]["end_line"], physical_lines)

        ledger = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
        self.assertTrue(all(item["passed"] for item in ledger["invariants"]), ledger["invariants"])


if __name__ == "__main__":
    unittest.main()
