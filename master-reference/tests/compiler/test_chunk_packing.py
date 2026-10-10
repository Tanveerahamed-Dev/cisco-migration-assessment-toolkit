"""Canonical compiler chunk packing has one owner (W64c).

``compiler/packing.py`` owns the per-group records-per-chunk caps. The writer
(``compiler/compiler.py``), the release intake (``release/compiler_bundle.py``)
and the projection (``build/projection/build.mjs``, which restates the table)
must derive packing from it. The release intake's accept and refuse cases for
``symbols`` live in ``tests/release/test_release_pipeline.py``; the
projection's live in ``tests/source/projection.test.mjs``.
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import sys
from pathlib import Path

import pytest

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from compiler import compiler as compiler_module  # noqa: E402
from compiler.compiler import RECORD_GROUPS  # noqa: E402
from compiler.packing import GROUP_CHUNK_RECORD_CAPS, effective_chunk_size  # noqa: E402

BUILD_MJS = MASTER_REFERENCE / "build" / "projection" / "build.mjs"
_JS_TABLE = re.compile(
    r"^export const COMPILER_GROUP_CHUNK_RECORD_CAPS = Object\.freeze\(\{\n"
    r"(?P<body>(?:  [a-z_]+: [0-9][0-9_]*,\n)*)"
    r"\}\);$",
    re.MULTILINE,
)
_JS_ENTRY = re.compile(r"  ([a-z_]+): ([0-9][0-9_]*),\n")
_SOURCE_SUFFIXES = {".py", ".mjs", ".js", ".cjs", ".ts", ".tsx"}
_SKIPPED_DIRECTORIES = {"node_modules", "tests", "dist", "public", ".vinext", ".wrangler", "__pycache__"}


def test_symbols_pack_at_500_and_source_text_at_one() -> None:
    assert dict(GROUP_CHUNK_RECORD_CAPS) == {"source_text": 1, "symbols": 500}
    assert effective_chunk_size("symbols", 2_000) == 500
    assert effective_chunk_size("symbols", 100_000) == 500
    assert effective_chunk_size("symbols", 500) == 500
    # A smaller shared size still applies to a capped group.
    assert effective_chunk_size("symbols", 3) == 3
    assert effective_chunk_size("source_text", 2_000) == 1
    assert effective_chunk_size("source_text", 1) == 1


def test_every_other_group_keeps_the_shared_chunk_size() -> None:
    assert set(GROUP_CHUNK_RECORD_CAPS) <= set(RECORD_GROUPS)
    uncapped = [group for group in RECORD_GROUPS if group not in GROUP_CHUNK_RECORD_CAPS]
    assert len(uncapped) == len(RECORD_GROUPS) - len(GROUP_CHUNK_RECORD_CAPS)
    for group in uncapped:
        for shared in (1, 3, 500, 501, 2_000, 100_000):
            assert effective_chunk_size(group, shared) == shared, group


def test_the_cap_table_is_immutable() -> None:
    with pytest.raises(TypeError):
        GROUP_CHUNK_RECORD_CAPS["symbols"] = 2_000  # type: ignore[index]
    assert GROUP_CHUNK_RECORD_CAPS["symbols"] == 500


@pytest.mark.parametrize("shared", [0, -1, True, 1.5, "2000", None])
def test_an_invalid_shared_chunk_size_is_refused(shared: object) -> None:
    for group in ("symbols", "source_text", "files"):
        with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
            effective_chunk_size(group, shared)  # type: ignore[arg-type]


def test_the_writer_packs_symbols_at_the_cap_and_every_other_group_unchanged(tmp_path: Path) -> None:
    def rows(kind: str, count: int) -> list[dict[str, str]]:
        return [{"id": f"urn:atlas:{kind}:{index:024x}"} for index in range(count)]

    records: dict[str, list[dict[str, str]]] = {group: [] for group in RECORD_GROUPS}
    records["symbols"] = rows("symbol", 1_001)
    records["configs"] = rows("config", 2_001)
    records["source_text"] = rows("source-text", 3)
    ledger = {
        "source_commit": "a" * 40,
        "source_tree_digest": "b" * 64,
        "head_tree_oid": "c" * 40,
        "index_digest": "d" * 64,
        "tracked_worktree_dirty": False,
        "graphify": {},
        "architecture_conformance": {},
    }
    output = tmp_path / "compiler"
    manifest = compiler_module._write_success(output, records, ledger, 2_000)

    # The manifest still records only the shared size; the caps are reader contract.
    assert manifest["chunk_size"] == 2_000
    chunk_counts = {
        group: [chunk["record_count"] for chunk in manifest["groups"][group]["chunks"]] for group in RECORD_GROUPS
    }
    assert chunk_counts["symbols"] == [500, 500, 1]
    assert chunk_counts["configs"] == [2_000, 1]
    assert chunk_counts["source_text"] == [1, 1, 1]
    assert chunk_counts["files"] == []
    for group in RECORD_GROUPS:
        size = effective_chunk_size(group, 2_000)
        count = len(records[group])
        assert manifest["groups"][group]["chunk_count"] == math.ceil(count / size)
    for index, expected in enumerate([500, 500, 1]):
        envelope = json.loads((output / f"chunks/symbols/{index:05d}.json").read_text(encoding="utf-8"))
        assert envelope["chunk_index"] == index
        assert envelope["chunk_count"] == 3
        assert envelope["record_count"] == expected == len(envelope["records"])


def test_python_and_javascript_packing_tables_agree() -> None:
    text = BUILD_MJS.read_text(encoding="utf-8")
    matches = list(_JS_TABLE.finditer(text))
    assert len(matches) == 1, "build.mjs must restate the packing table exactly once"
    assert text.count("COMPILER_GROUP_CHUNK_RECORD_CAPS =") == 1
    body = matches[0].group("body")
    entries = _JS_ENTRY.findall(body)
    assert "".join(f"  {name}: {value},\n" for name, value in entries) == body
    restated = {name: int(value.replace("_", "")) for name, value in entries}
    assert len(restated) == len(entries), "build.mjs restates a packing cap twice"
    assert restated == dict(GROUP_CHUNK_RECORD_CAPS)


def _python_calls_owner(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            function = node.func
            if (isinstance(function, ast.Name) and function.id == "effective_chunk_size") or (
                isinstance(function, ast.Attribute) and function.attr == "effective_chunk_size"
            ):
                return True
    return False


def _javascript_calls_owner(source: str) -> bool:
    calls = len(re.findall(r"\bcompilerEffectiveChunkSize\(", source))
    definitions = len(re.findall(r"\bfunction compilerEffectiveChunkSize\(", source))
    return calls > definitions


def test_every_source_that_reads_the_shared_chunk_size_derives_packing_from_the_owner() -> None:
    # Canonical packing cannot be derived without the manifest's shared
    # ``chunk_size``, so every non-test source that names it must take the
    # per-group size from the owner rather than restating a cap.
    # ``compiler/__main__.py`` only forwards the CLI value to
    # ``compile_repository``; ``compiler/packing.py`` is the owner.
    exempt = {"compiler/__main__.py", "compiler/packing.py"}
    readers: set[str] = set()
    offenders: list[str] = []
    for directory, subdirectories, names in os.walk(MASTER_REFERENCE):
        subdirectories[:] = sorted(name for name in subdirectories if name not in _SKIPPED_DIRECTORIES)
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix not in _SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(MASTER_REFERENCE).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            if relative in exempt or re.search(r"\bchunk_size\b", text) is None:
                continue
            readers.add(relative)
            calls_owner = _python_calls_owner(text) if path.suffix == ".py" else _javascript_calls_owner(text)
            if not calls_owner:
                offenders.append(relative)
    # Positive control: the scan reaches every known reader.
    assert {"compiler/compiler.py", "release/compiler_bundle.py", "build/projection/build.mjs"} <= readers
    assert offenders == [], "these sources read chunk_size without deriving packing from compiler/packing.py"
