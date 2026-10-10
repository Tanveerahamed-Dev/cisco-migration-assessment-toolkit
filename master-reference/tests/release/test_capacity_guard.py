"""W64-0 capacity guard: thresholds, messages, fail-closed inputs and trend arithmetic.

These tests never run the compiler, the projection builder or ``cli build``.
They feed the guard small synthetic inputs, check its counting against
independent recursive reference implementations, and read the real owner
constants from their source files.
"""

from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

import release.compiler_bundle as compiler_bundle  # noqa: E402
from cli import capacity  # noqa: E402
from compiler.model import canonical_json  # noqa: E402

UTC = timezone.utc
TIME_REPORT = (
    '\tCommand being timed: "python -m cli build"\n'
    "\tUser time (seconds): 600.00\n"
    "\tElapsed (wall clock) time (h:mm:ss or m:ss): 11:50.12\n"
    "\tMaximum resident set size (kbytes): {rss}\n"
    "\tPage size (bytes): 4096\n"
    "\tExit status: 0\n"
)
MEMINFO = "MemTotal:       16000000 kB\nMemFree:         9000000 kB\n"
LINE_RECORDS = [
    {
        "flag": True,
        "id": "urn:atlas:line:000000000000000000000001",
        "line": 1,
        "nested": {"k": [1, 2]},
        "owner": None,
        "ratio": 0.5,
        "tags": ["a", "b"],
        "text": "s" * 300 + "é\n",
    },
    {
        "flag": False,
        "id": "urn:atlas:line:000000000000000000000002",
        "line": 2,
        "nested": {},
        "owner": "f",
        "ratio": -1.25,
        "tags": [],
        "text": "",
    },
]
GRAPH_RECORDS = [{"id": "g1", "label": "node"}]


# --------------------------------------------------------------------------- reference implementations


def _reference_values(value: Any) -> int:
    """Every value counts once; object keys never count (the projection and receipt readers)."""

    if isinstance(value, dict):
        return 1 + sum(_reference_values(child) for child in value.values())
    if isinstance(value, list):
        return 1 + sum(_reference_values(child) for child in value)
    return 1


def _reference_release_scan(value: Any) -> tuple[int, int]:
    """Every item counts once, object keys included; every string adds its UTF-8 bytes."""

    if isinstance(value, dict):
        values = 1 + len(value)
        size = sum(len(key.encode("utf-8")) for key in value)
        for child in value.values():
            child_values, child_size = _reference_release_scan(child)
            values += child_values
            size += child_size
        return values, size
    if isinstance(value, list):
        values, size = 1, 0
        for child in value:
            child_values, child_size = _reference_release_scan(child)
            values += child_values
            size += child_size
        return values, size
    if isinstance(value, str):
        return 1, len(value.encode("utf-8"))
    return 1, 0


def _reference_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [*value.keys(), *(text for child in value.values() for text in _reference_strings(child))]
    if isinstance(value, list):
        return [text for child in value for text in _reference_strings(child)]
    return [value] if isinstance(value, str) else []


def _token_bytes(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8"))


# --------------------------------------------------------------------------- synthetic inputs


def _write_json(root: Path, relative: str, value: object, *, canonical: bool = True) -> dict[str, Any]:
    raw = canonical_json(value) if canonical else (json.dumps(value, indent=1) + "\n").encode("utf-8")
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"bytes": len(raw), "path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def _envelope(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "chunk_count": 1,
        "chunk_index": 0,
        "record_count": len(records),
        "record_type": name,
        "records": records,
        "records_digest": "e" * 64,
        "schema_version": "1.2.0",
        "source_commit": "c" * 40,
        "source_tree_digest": "d" * 64,
    }


def _compiler_output(tmp_path: Path, *, canonical_lines: bool = True) -> Path:
    root = tmp_path / "atlas-compiler"
    groups: dict[str, Any] = {}
    for name, records in (("graph_nodes", GRAPH_RECORDS), ("lines", LINE_RECORDS)):
        relative = f"chunks/{name}/00000.json"
        receipt = _write_json(
            root, relative, _envelope(name, records), canonical=canonical_lines or name != "lines"
        )
        groups[name] = {
            "chunk_count": 1,
            "chunks": [{**receipt, "record_count": len(records)}],
            "record_count": len(records),
            "records_digest": "f" * 64,
        }
    completeness = _write_json(root, "completeness.json", {"notes": ["a"], "status": "ok"})
    _write_json(
        root,
        "manifest.json",
        {
            "chunk_size": 2000,
            "completeness": completeness,
            "groups": groups,
            "schema_version": "1.2.0",
            "status": "complete",
        },
    )
    return root


def _gzip_json(path: Path, value: object) -> bytes:
    raw = json.dumps(value, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw))
    return raw


def _dist(tmp_path: Path, *, original_bytes: int = 300) -> Path:
    dist = tmp_path / "dist"
    projection = dist / "client" / "atlas-projection"
    _gzip_json(
        projection / "compression-manifest.json.gz",
        {
            "compressedBytes": 120,
            "modules": [
                {"compressedBytes": 80, "originalBytes": 200, "path": "records/a.mjs"},
                {"compressedBytes": 40, "originalBytes": 100, "path": "source/b.mjs"},
            ],
            "originalBytes": original_bytes,
        },
    )
    _gzip_json(projection / "projection-manifest.json.gz", {"modules": [{"module": "records/a.mjs"}]})
    _gzip_json(
        dist / "deployment-manifest.json.gz",
        {"members": [{"bytes": 10, "path": "index.html", "sha256": "0" * 64}, {"bytes": 7, "path": "a.js", "sha256": "1" * 64}]},
    )
    return dist


def _census_stdout(scanned: int = 1_000, *, limit: int | None = None) -> str:
    census = {
        "chunk_bytes": scanned - 100,
        "chunk_count": 2,
        "identity_depth_source_bytes": 100,
        "limit_bytes": compiler_bundle._MAX_COMPILER_CHUNK_BYTES if limit is None else limit,
        "local_identity_scan_performed": True,
        "scanned_bytes": scanned,
    }
    return json.dumps({"compiler_chunk_census": census, "ok": True, "release_status": "BLOCK"}, indent=2) + "\n"


def _full_arguments(tmp_path: Path, *, run_id: str = "11", now: str = "2026-10-10T00:00:00Z") -> list[str]:
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "cli-build.stdout").write_text(_census_stdout(), encoding="utf-8")
    (inputs / "compiler.time").write_text(TIME_REPORT.format(rss=1_000), encoding="utf-8")
    (inputs / "meminfo").write_text(MEMINFO, encoding="utf-8")
    compiler = tmp_path / "atlas-compiler"
    if not compiler.exists():
        _compiler_output(tmp_path)
    dist = tmp_path / "dist"
    if not dist.exists():
        _dist(tmp_path)
    return [
        "--compiler-output", str(compiler),
        "--cli-build-stdout", str(inputs / "cli-build.stdout"),
        "--cli-build-stderr", str(inputs / "cli-build.stderr"),
        "--dist", str(dist),
        "--projection-dir", str(tmp_path / "public"),
        "--rss", f"compiler={inputs / 'compiler.time'}",
        "--meminfo", str(inputs / "meminfo"),
        "--summary", str(tmp_path / f"summary-{run_id}.md"),
        "--sha", "a" * 40,
        "--run-id", run_id,
        "--ref", "refs/heads/main",
        "--event", "push",
        "--now", now,
    ]


def _wall(value: int, limit: int, **overrides: str) -> capacity.Wall:
    fields = {
        "id": "projection.expanded_bytes",
        "title": "Projection expanded bytes",
        "unit": "B",
        "owner": capacity.EXPANDED_PROJECTION.label,
        "remedy": "trim the projection",
    }
    fields.update(overrides)
    wall = capacity.Wall(**fields)
    wall.measure(value, limit, basis="test")
    return wall


def _report(walls: list[capacity.Wall], input_errors: list[dict[str, str]] | None = None) -> capacity.Report:
    return capacity.Report(
        generated_at="2026-10-10T00:00:00Z",
        run={},
        walls=walls,
        input_errors=input_errors or [],
        field_census=None,
        owner_constants={},
        baseline_state="none",
        baseline_note="no baseline",
        history=[],
        trends={},
    )


def _row(at: str, run_id: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"at": at, "event": "push", "run_id": run_id, "sha": "a" * 40, "values": values}


# --------------------------------------------------------------------------- thresholds and messages


@pytest.mark.parametrize(
    ("value", "status"),
    [(0, "ok"), (8_499, "ok"), (8_500, "warn"), (9_499, "warn"), (9_500, "fail"), (10_000, "fail"), (12_000, "fail")],
)
def test_threshold_boundaries_are_exact(value: int, status: str) -> None:
    # 84.99 %, 85 %, 94.99 % and 95 % of a 10,000-unit limit.
    assert capacity.classify(value, 10_000) == status


def test_thresholds_are_rational_on_a_real_limit() -> None:
    limit = compiler_bundle._MAX_COMPILER_CHUNK_BYTES
    warn_floor = limit * 85 // 100
    fail_floor = limit * 95 // 100
    assert capacity.classify(warn_floor, limit) == ("warn" if warn_floor * 100 == limit * 85 else "ok")
    assert capacity.classify(warn_floor + 1, limit) == "warn"
    assert capacity.classify(fail_floor, limit) == ("fail" if fail_floor * 100 == limit * 95 else "warn")
    assert capacity.classify(fail_floor + 1, limit) == "fail"


def test_percent_display_truncates_rather_than_rounding_across_a_threshold() -> None:
    assert capacity.format_percent(capacity.percent_hundredths(84_999, 100_000)) == "84.99"
    assert capacity.format_percent(capacity.percent_hundredths(85_000, 100_000)) == "85.00"
    assert capacity.format_percent(capacity.percent_hundredths(94_999, 100_000)) == "94.99"
    assert capacity.classify(94_999, 100_000) == "warn"
    assert capacity.format_percent(capacity.percent_hundredths(95_000, 100_000)) == "95.00"


@pytest.mark.parametrize(("value", "limit"), [(-1, 10), (1, 0), (True, 10), (1, True), (1.0, 10), (1, 10.0)])
def test_classify_refuses_a_malformed_measurement(value: object, limit: object) -> None:
    with pytest.raises(capacity.CapacityInputError):
        capacity.classify(value, limit)  # type: ignore[arg-type]


def test_fail_message_names_wall_value_limit_owner_and_remedy() -> None:
    wall = _wall(2_040_109_466, 2_147_483_648)
    assert wall.status == "fail"
    message = capacity.wall_message(wall)
    assert "Projection expanded bytes [projection.expanded_bytes]" in message
    assert "is at 95.00% of its limit (fail at 95%)" in message
    assert "value=2,040,109,466 B" in message
    assert "limit=2,147,483,648 B" in message
    assert "build/deployment-manifest.mjs::MAX_EXPANDED_PROJECTION_BYTES" in message
    assert "Remedy: trim the projection." in message
    [line] = capacity.annotations([wall], [])
    assert line.startswith("::error title=Capacity wall projection.expanded_bytes::")
    assert "95.00%25 of its limit" in line
    assert "%" not in line.replace("%25", "").replace("%0A", "").replace("%0D", "")


def test_warn_message_and_annotation() -> None:
    wall = _wall(2_040_109_465, 2_147_483_648)
    assert wall.status == "warn"
    assert "(warn at 85%)" in capacity.wall_message(wall)
    [line] = capacity.annotations([wall], [])
    assert line.startswith("::warning title=Capacity warning projection.expanded_bytes::")


def test_ok_wall_emits_no_annotation() -> None:
    assert capacity.annotations([_wall(1, 100)], []) == []


def test_unmeasured_wall_names_the_reason_and_fails_closed() -> None:
    wall = _wall(1, 100)
    wall.unmeasured("compression receipt is absent")
    assert wall.status == "unmeasured"
    message = capacity.wall_message(wall)
    assert "was not measured: compression receipt is absent" in message
    assert capacity.EXPANDED_PROJECTION.label in message
    [line] = capacity.annotations([wall], [])
    assert line.startswith("::error title=Capacity input projection.expanded_bytes::")


@pytest.mark.parametrize(
    ("statuses", "errors", "expected"),
    [
        (("ok",), [], capacity.EXIT_OK),
        (("ok", "warn"), [], capacity.EXIT_OK),
        (("ok", "fail"), [], capacity.EXIT_WALL),
        (("ok", "unmeasured"), [], capacity.EXIT_INPUT),
        (("fail", "unmeasured"), [], capacity.EXIT_WALL),
        (("ok",), [{"source": "field census", "error": "x"}], capacity.EXIT_INPUT),
    ],
)
def test_exit_code_follows_the_worst_wall(statuses: tuple[str, ...], errors: list[dict[str, str]], expected: int) -> None:
    values = {"ok": 10, "warn": 90, "fail": 99, "unmeasured": 10}
    walls = []
    for index, status in enumerate(statuses):
        wall = _wall(values[status], 100, id=f"w{index}")
        if status == "unmeasured":
            wall.unmeasured("absent")
        walls.append(wall)
    assert _report(walls, errors).exit_code == expected


# --------------------------------------------------------------------------- owner constants


def test_python_owner_constants_equal_the_imported_owner_values() -> None:
    owners = capacity.OwnerTable()
    assert owners.value(capacity.RELEASE_CENSUS) == compiler_bundle._MAX_COMPILER_CHUNK_BYTES
    assert owners.value(capacity.RELEASE_JSON_BYTES) == compiler_bundle._MAX_COMPILER_JSON_BYTES
    assert owners.value(capacity.RELEASE_SCAN_VALUES) == compiler_bundle._LOCAL_SCAN_MAX_VALUES
    assert owners.value(capacity.RELEASE_SCAN_BYTES) == compiler_bundle._LOCAL_SCAN_MAX_TOTAL_BYTES


def test_every_registered_owner_resolves_from_its_source() -> None:
    owners = capacity.OwnerTable()
    for owner in capacity.OWNERS:
        assert owners.value(owner) > 0, owner.label
    assert set(owners.resolved()) == {owner.label for owner in capacity.OWNERS}


def test_javascript_owner_constants_parse_integer_products_only() -> None:
    owner = capacity.Owner("build/x.mjs", "LIMIT")
    assert capacity.javascript_owner_constant("const LIMIT = 32 * 1024 * 1024;\n", owner) == 32 * 1024 * 1024
    assert capacity.javascript_owner_constant("export const LIMIT = 5_000_000;\r\n", owner) == 5_000_000
    assert capacity.javascript_owner_constant("const LIMIT_X = 1;\nconst LIMIT = 7;\n", owner) == 7
    for text in (
        "const OTHER = 1;\n",
        "function f() {\n  const LIMIT = 4;\n}\n",
        "const LIMIT = 1;\nconst LIMIT = 2;\n",
        "const LIMIT = OTHER * 2;\n",
        "const LIMIT = 2 ** 20;\n",
        "const LIMIT = 1__0;\n",
    ):
        with pytest.raises(capacity.CapacityInputError):
            capacity.javascript_owner_constant(text, owner)


def test_python_owner_constants_parse_integer_products_only() -> None:
    owner = capacity.Owner("release/x.py", "LIMIT")
    assert capacity.python_owner_constant("LIMIT = 2304 * 1024 * 1024\n", owner) == 2304 * 1024 * 1024
    assert capacity.python_owner_constant("LIMIT: int = 5_000_000\n", owner) == 5_000_000
    for text in (
        "OTHER = 1\n",
        "def f():\n    LIMIT = 4\n",
        "LIMIT = 1\nLIMIT = 2\n",
        "LIMIT = 1\nLIMIT += 1\n",
        "LIMIT = OTHER * 2\n",
        "LIMIT = 2 ** 20\n",
        "LIMIT = 1.5\n",
        "LIMIT = True\n",
        "LIMIT = (\n",
    ):
        with pytest.raises(capacity.CapacityInputError):
            capacity.python_owner_constant(text, owner)


def test_an_unreadable_or_non_positive_owner_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "zero.py").write_text("LIMIT = 0\n", encoding="utf-8")
    with pytest.raises(capacity.CapacityInputError):
        capacity.read_owner_constant(capacity.Owner("zero.py", "LIMIT"), tmp_path)
    with pytest.raises(capacity.CapacityInputError):
        capacity.read_owner_constant(capacity.Owner("absent.mjs", "LIMIT"), tmp_path)


def test_release_scan_groups_match_the_release_owner() -> None:
    source = inspect.getsource(compiler_bundle._scan_generated_local_identities)
    expected = "for group_name in (" + ", ".join(f'"{name}"' for name in capacity.RELEASE_SCAN_GROUPS) + ")"
    assert expected in source


def test_receipt_locations_match_their_owners() -> None:
    compress = (MASTER_REFERENCE / "build" / "compress-projection.mjs").read_text(encoding="utf-8")
    deploy = (MASTER_REFERENCE / "build" / "deployment-manifest.mjs").read_text(encoding="utf-8")
    assert f'const RECEIPT_NAME = "{capacity.COMPRESSION_RECEIPT}";' in compress
    assert 'const PROJECTION_MANIFEST_NAME = "projection-manifest.json";' in compress
    assert "const PROJECTION_MANIFEST_REPRESENTATION_NAME = `${PROJECTION_MANIFEST_NAME}.gz`;" in compress
    assert capacity.PROJECTION_RECEIPT == "projection-manifest.json.gz"
    assert f'const PROJECTION_DIRECTORY = "{capacity.PROJECTION_DIRECTORY}";' in deploy
    assert 'const MANIFEST_SOURCE_NAME = "deployment-manifest.json";' in deploy
    assert "const MANIFEST_NAME = `${MANIFEST_SOURCE_NAME}.gz`;" in deploy
    assert capacity.DEPLOYMENT_RECEIPT == "deployment-manifest.json.gz"


# --------------------------------------------------------------------------- counting


def test_value_counts_follow_each_bounded_reader() -> None:
    value = {"a": [1, "x", {}], "b": None}
    assert capacity.JsonShape().measure(value, "w") == _reference_values(value) == 6
    assert capacity.release_scan_census(value) == _reference_release_scan(value) == (8, 3)


def test_string_tokens_count_quotes_escapes_utf8_and_keys() -> None:
    shape = capacity.JsonShape()
    shape.measure({"k": "a\nb", "é": "z"}, "first")
    assert (shape.max_string_bytes, shape.max_string_where) == (6, "first")
    shape.measure(["x" * 10], "second")
    assert (shape.max_string_bytes, shape.max_string_where) == (12, "second")
    shape.measure(["y" * 10, "é" * 4], "third")
    assert (shape.max_string_bytes, shape.max_string_where) == (12, "second")


def test_compiler_scan_measures_every_file_against_reference_counts(tmp_path: Path) -> None:
    root = _compiler_output(tmp_path)
    scan = capacity.scan_compiler_output(root)
    lines_raw = (root / "chunks" / "lines" / "00000.json").read_bytes()
    graph_raw = (root / "chunks" / "graph_nodes" / "00000.json").read_bytes()
    assert scan.groups["lines"]["max_chunk_bytes"] == len(lines_raw)
    assert scan.groups["lines"]["max_chunk"] == "chunks/lines/00000.json"
    assert scan.groups["graph_nodes"]["records"] == 1
    documents = {
        path.relative_to(root).as_posix(): json.loads(path.read_bytes())
        for path in sorted(root.rglob("*.json"))
    }
    expected_values = max((_reference_values(value), name) for name, value in documents.items())
    assert scan.max_values == expected_values
    longest = max(_token_bytes(text) for value in documents.values() for text in _reference_strings(value))
    assert scan.max_string == (longest, "chunks/lines/00000.json")
    assert longest == 306
    completeness = _reference_release_scan(documents["completeness.json"])
    graph = _reference_release_scan(GRAPH_RECORDS[0])
    assert (scan.release_scan_values, scan.release_scan_bytes) == (
        completeness[0] + graph[0],
        completeness[1] + graph[1],
    )
    assert scan.owner_documents == {
        "manifest.json": (root / "manifest.json").stat().st_size,
        "completeness.json": (root / "completeness.json").stat().st_size,
    }
    assert len(graph_raw) == scan.groups["graph_nodes"]["max_chunk_bytes"]


def test_field_census_is_exact_and_reconciles_with_chunk_bytes(tmp_path: Path) -> None:
    root = _compiler_output(tmp_path)
    scan = capacity.scan_compiler_output(root)
    assert scan.census_error is None
    census = scan.census["lines"]
    expected: dict[str, list[int]] = {}
    for record in LINE_RECORDS:
        for key, value in record.items():
            entry = expected.setdefault(key, [0, 0])
            entry[0] += 1
            entry[1] += len(canonical_json({key: value})) - 3
    assert census.fields == expected
    record_bytes = sum(len(canonical_json(record)) - 1 for record in LINE_RECORDS)
    assert census.record_bytes == record_bytes
    assert census.record_structure_bytes == record_bytes - sum(size for _, size in expected.values())
    assert census.chunk_bytes == (root / "chunks" / "lines" / "00000.json").stat().st_size
    assert (census.chunks, census.records) == (1, 2)
    summary = census.as_dict("lines")
    assert summary["envelope_bytes"] == census.chunk_bytes - record_bytes
    assert [row["field"] for row in summary["fields"]][0] == "text"


def test_a_non_canonical_chunk_fails_the_census_closed_but_keeps_the_walls(tmp_path: Path) -> None:
    root = _compiler_output(tmp_path, canonical_lines=False)
    walls, census, error = capacity.compiler_walls(capacity.OwnerTable(), root)
    assert census is None
    assert error is not None and "does not reconcile" in error
    by_id = {wall.id: wall for wall in walls}
    assert by_id["chunk_bytes.lines"].status == "ok"


def test_a_chunk_that_differs_from_its_receipt_fails_closed(tmp_path: Path) -> None:
    root = _compiler_output(tmp_path)
    with (root / "chunks" / "lines" / "00000.json").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(capacity.CapacityInputError, match="differs from its manifest byte receipt"):
        capacity.scan_compiler_output(root)
    walls, census, _ = capacity.compiler_walls(capacity.OwnerTable(), root)
    assert census is None
    assert {wall.status for wall in walls} == {"unmeasured"}


def test_a_missing_chunk_or_a_wrong_record_count_fails_closed(tmp_path: Path) -> None:
    root = _compiler_output(tmp_path)
    manifest = json.loads((root / "manifest.json").read_bytes())
    manifest["groups"]["lines"]["record_count"] = 3
    (root / "manifest.json").write_bytes(canonical_json(manifest))
    with pytest.raises(capacity.CapacityInputError, match="different record count"):
        capacity.scan_compiler_output(root)
    (root / "chunks" / "lines" / "00000.json").unlink()
    with pytest.raises(capacity.CapacityInputError, match="is absent"):
        capacity.scan_compiler_output(root)


def test_an_absent_compiler_output_leaves_every_compiler_wall_unmeasured(tmp_path: Path) -> None:
    walls, census, error = capacity.compiler_walls(capacity.OwnerTable(), tmp_path / "absent")
    assert census is None and error is None
    assert walls and {wall.status for wall in walls} == {"unmeasured"}


# --------------------------------------------------------------------------- census, projection, memory, disk


def test_census_wall_reads_the_cli_build_success_json(tmp_path: Path) -> None:
    stdout = tmp_path / "cli-build.stdout"
    stdout.write_text("pdf: rendered\n" + _census_stdout(2_000), encoding="utf-8")
    wall = capacity.census_wall(capacity.OwnerTable(), stdout, tmp_path / "absent.stderr")
    assert (wall.value, wall.limit, wall.status) == (2_000, compiler_bundle._MAX_COMPILER_CHUNK_BYTES, "ok")
    assert "success JSON" in wall.basis


def test_census_wall_reads_a_census_refusal_as_a_failing_lower_bound(tmp_path: Path) -> None:
    limit = compiler_bundle._MAX_COMPILER_CHUNK_BYTES
    stderr = tmp_path / "cli-build.stderr"
    error = (
        "compiler chunk byte census exceeds the exhaustive privacy scan's resource ceiling: "
        f"scanned_bytes={limit + 5}; limit={limit}; group=lines; index=3"
    )
    stderr.write_text(json.dumps({"error": error, "ok": False}, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (tmp_path / "cli-build.stdout").write_text("", encoding="utf-8")
    wall = capacity.census_wall(capacity.OwnerTable(), tmp_path / "cli-build.stdout", stderr)
    assert (wall.value, wall.status) == (limit + 5, "fail")
    assert "lower bound" in wall.basis


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json\n",
        json.dumps({"ok": True, "compiler_chunk_census": None}),
        json.dumps({"ok": False, "compiler_chunk_census": {"scanned_bytes": 1}}),
    ],
)
def test_census_wall_fails_closed_without_a_census(tmp_path: Path, stdout: str) -> None:
    path = tmp_path / "cli-build.stdout"
    path.write_text(stdout, encoding="utf-8")
    wall = capacity.census_wall(capacity.OwnerTable(), path, tmp_path / "absent.stderr")
    assert wall.status == "unmeasured"


def test_census_wall_refuses_a_limit_or_sum_that_disagrees(tmp_path: Path) -> None:
    path = tmp_path / "cli-build.stdout"
    path.write_text(_census_stdout(limit=123), encoding="utf-8")
    wall = capacity.census_wall(capacity.OwnerTable(), path, None)
    assert wall.status == "unmeasured" and "differs from" in (wall.error or "")
    document = json.loads(_census_stdout())
    document["compiler_chunk_census"]["chunk_bytes"] += 1
    path.write_text(json.dumps(document), encoding="utf-8")
    wall = capacity.census_wall(capacity.OwnerTable(), path, None)
    assert wall.status == "unmeasured" and "does not add up" in (wall.error or "")


def test_projection_walls_read_the_receipts(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    owners = capacity.OwnerTable()
    walls = {wall.id: wall for wall in capacity.projection_walls(owners, dist, tmp_path / "public")}
    assert (walls["projection.expanded_bytes"].value, walls["projection.expanded_bytes"].limit) == (
        300,
        owners.value(capacity.EXPANDED_PROJECTION),
    )
    assert walls["projection.compressed_bytes"].value == 120
    assert walls["projection.compressed_bytes"].limit == owners.value(capacity.COMPRESSED_PROJECTION)
    assert walls["projection.module_max_expanded_bytes"].value == 200
    assert walls["projection.module_max_compressed_bytes"].value == 80
    assert walls["deployment.member_max_bytes"].value == 10
    assert "index.html" in walls["deployment.member_max_bytes"].detail
    raw = gzip.decompress((dist / "client" / "atlas-projection" / "compression-manifest.json.gz").read_bytes())
    assert walls["receipt.compression.bytes"].value == len(raw)
    assert walls["receipt.compression.values"].value == _reference_values(json.loads(raw))
    assert {wall.status for wall in walls.values()} == {"ok"}


def test_projection_aggregates_that_disagree_with_their_modules_fail_closed(tmp_path: Path) -> None:
    dist = _dist(tmp_path, original_bytes=999)
    walls = {wall.id: wall for wall in capacity.projection_walls(capacity.OwnerTable(), dist, tmp_path / "public")}
    assert walls["projection.expanded_bytes"].status == "unmeasured"
    assert "differ from its module sums" in (walls["projection.expanded_bytes"].error or "")
    assert walls["projection.compressed_bytes"].status == "unmeasured"


def test_projection_tree_measures_the_expanded_wall_without_a_receipt(tmp_path: Path) -> None:
    public = tmp_path / "public"
    (public / "records").mkdir(parents=True)
    (public / "records" / "a.mjs").write_bytes(b"x" * 10)
    (public / "b.mjs").write_bytes(b"y" * 20)
    (public / "projection-manifest.json").write_bytes(b"{}")
    walls = {wall.id: wall for wall in capacity.projection_walls(capacity.OwnerTable(), tmp_path / "dist", public)}
    assert walls["projection.expanded_bytes"].value == 30
    assert "receipt is absent" in walls["projection.expanded_bytes"].basis
    assert walls["projection.compressed_bytes"].status == "unmeasured"
    assert walls["receipt.deployment.bytes"].status == "unmeasured"


def test_a_corrupt_gzip_receipt_fails_closed(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    receipt = dist / "client" / "atlas-projection" / "compression-manifest.json.gz"
    receipt.write_bytes(receipt.read_bytes()[:-9])
    walls = {wall.id: wall for wall in capacity.projection_walls(capacity.OwnerTable(), dist, None)}
    assert walls["receipt.compression.bytes"].status == "unmeasured"
    assert walls["projection.expanded_bytes"].status == "unmeasured"


def test_gnu_time_and_meminfo_parsing() -> None:
    report = capacity.parse_gnu_time(TIME_REPORT.format(rss=12_004_760), "cli_build")
    assert report == {"max_rss_kib": 12_004_760, "elapsed": "11:50.12", "exit_status": 0, "signal": None}
    killed = "\tCommand terminated by signal 9\n" + TIME_REPORT.format(rss=15_000_000)
    assert capacity.parse_gnu_time(killed, "cli_build")["signal"] == 9
    assert capacity.parse_memtotal(MEMINFO) == 16_000_000
    for text in ("", TIME_REPORT.format(rss=1) + TIME_REPORT.format(rss=2), "Maximum resident set size (kbytes): x\n"):
        with pytest.raises(capacity.CapacityInputError):
            capacity.parse_gnu_time(text, "cli_build")
    for text in ("", "MemTotal: 0 kB\n", MEMINFO + MEMINFO):
        with pytest.raises(capacity.CapacityInputError):
            capacity.parse_memtotal(text)


def test_rss_walls_measure_against_memtotal_and_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "cli.time").write_text(TIME_REPORT.format(rss=15_300_000), encoding="utf-8")
    (tmp_path / "meminfo").write_text(MEMINFO, encoding="utf-8")
    walls = capacity.rss_walls(
        [("cli_build", tmp_path / "cli.time"), ("projection", tmp_path / "absent.time")], tmp_path / "meminfo"
    )
    assert (walls[0].id, walls[0].value, walls[0].limit, walls[0].status) == (
        "peak_rss.cli_build",
        15_300_000,
        16_000_000,
        "fail",
    )
    assert walls[1].status == "unmeasured"
    [wall] = capacity.rss_walls([("cli_build", tmp_path / "cli.time")], tmp_path / "absent-meminfo")
    assert wall.status == "unmeasured" and "meminfo" in (wall.error or "")


def test_disk_walls_share_one_row_per_file_system() -> None:
    usage = {Path("a"): (100, 60, 30), Path("b"): (100, 60, 30), Path("c"): (50, 49, 1)}
    devices = {Path("a"): 1, Path("b"): 1, Path("c"): 2}
    walls = capacity.disk_walls(
        [("runner_temp", Path("a")), ("workspace", Path("b")), ("scratch", Path("c"))],
        usage=lambda path: usage[path],
        device=lambda path: devices[path],
    )
    assert [wall.id for wall in walls] == ["disk.runner_temp", "disk.scratch"]
    assert (walls[0].value, walls[0].limit, walls[0].status) == (60, 90, "ok")
    assert "also holds workspace" in walls[0].detail
    assert walls[1].status == "fail"


# --------------------------------------------------------------------------- trend


def test_growth_rate_and_days_to_each_threshold() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    slope = capacity.growth_per_day([(start + timedelta(days=day), 100 + 10 * day) for day in range(3)])
    assert slope == pytest.approx(10.0)
    assert capacity.days_until(120, 200, capacity.WARN_AT, slope) == pytest.approx(5.0)
    assert capacity.days_until(120, 200, Fraction(1), slope) == pytest.approx(8.0)
    assert capacity.days_until(170, 200, capacity.WARN_AT, slope) == 0.0
    assert capacity.days_until(120, 200, capacity.WARN_AT, -1.0) is None
    assert capacity.days_until(120, 200, capacity.WARN_AT, 0.0) is None
    assert capacity.days_until(120, 200, capacity.WARN_AT, None) is None


def test_growth_needs_two_points_over_the_minimum_span() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    assert capacity.growth_per_day([]) is None
    assert capacity.growth_per_day([(start, 1)]) is None
    assert capacity.growth_per_day([(start, 1), (start + timedelta(hours=1), 2)]) is None
    assert capacity.growth_per_day([(start, 1), (start + timedelta(hours=12), 2)]) == pytest.approx(2.0)


def test_wall_trend_reports_delta_since_main_and_days_left() -> None:
    wall = _wall(120, 200, id="w")
    baseline = [
        _row("2026-10-01T00:00:00Z", "1", {"w": {"limit": 200, "value": 100}}),
        _row("2026-10-02T00:00:00Z", "2", {"w": {"limit": 200, "value": 110}}),
    ]
    current = capacity.history_row(
        [wall], datetime(2026, 10, 3, tzinfo=UTC), {"event": "pull_request", "run_id": "3", "sha": "b" * 40}
    )
    history = capacity.merge_history(baseline, current)
    trend = capacity.wall_trend(wall, history, baseline)
    assert (trend["baseline_value"], trend["delta"], trend["points"]) == (110, 10, 3)
    assert trend["growth_per_day"] == pytest.approx(10.0)
    assert trend["days_to_warn"] == pytest.approx(5.0)
    assert trend["days_to_limit"] == pytest.approx(8.0)
    unmeasured = _wall(1, 2, id="w")
    unmeasured.unmeasured("absent")
    assert capacity.wall_trend(unmeasured, history, baseline)["delta"] is None


def test_history_keeps_thirty_rows_and_one_row_per_run() -> None:
    rows = [_row(f"2026-09-{day:02d}T00:00:00Z", str(day), {}) for day in range(1, 31)]
    merged = capacity.merge_history(rows, _row("2026-10-01T00:00:00Z", "31", {}))
    assert len(merged) == capacity.HISTORY_LIMIT == 30
    assert (merged[0]["run_id"], merged[-1]["run_id"]) == ("2", "31")
    rerun = capacity.merge_history(rows[:3], _row("2026-10-01T00:00:00Z", "2", {}))
    assert [row["run_id"] for row in rerun] == ["1", "3", "2"]


def test_a_missing_baseline_is_reported_and_never_fails(tmp_path: Path) -> None:
    rows, state, note = capacity.load_baseline(tmp_path / "absent.json")
    assert (rows, state) == ([], "none") and note.startswith("no baseline")
    rows, state, note = capacity.load_baseline(None)
    assert (rows, state) == ([], "none")


@pytest.mark.parametrize(
    "document",
    [
        "{not json",
        json.dumps({"schema": "other/1", "history": [_row("2026-10-01T00:00:00Z", "1", {})]}),
        json.dumps({"schema": capacity.SCHEMA, "history": []}),
        json.dumps({"schema": capacity.SCHEMA, "history": [_row("yesterday", "1", {})]}),
        json.dumps({"schema": capacity.SCHEMA, "history": [_row("2026-10-01T00:00:00", "1", {})]}),
        json.dumps({"schema": capacity.SCHEMA, "history": [_row("2026-10-01T00:00:00Z", "1", {"w": {"value": -1, "limit": 2}})]}),
        json.dumps({"schema": capacity.SCHEMA, "history": [_row("2026-10-01T00:00:00Z", "1", {"w": {"value": 1}})]}),
        json.dumps({"schema": capacity.SCHEMA, "history": [{**_row("2026-10-01T00:00:00Z", "1", {}), "x": 1}]}),
        json.dumps(
            {"schema": capacity.SCHEMA, "history": [_row("2026-10-01T00:00:00Z", str(n), {}) for n in range(31)]}
        ),
    ],
)
def test_a_malformed_baseline_is_refused_and_never_fails(tmp_path: Path, document: str) -> None:
    path = tmp_path / "capacity.json"
    path.write_text(document, encoding="utf-8")
    rows, state, note = capacity.load_baseline(path)
    assert (rows, state) == ([], "refused")
    assert note.startswith("baseline refused")


def test_end_to_end_without_baseline_then_with_the_previous_record(tmp_path: Path) -> None:
    first = tmp_path / "first" / "capacity.json"
    assert capacity.main([*_full_arguments(tmp_path, run_id="11"), "--output", str(first)]) == capacity.EXIT_OK
    document = json.loads(first.read_text(encoding="utf-8"))
    assert document["schema"] == capacity.SCHEMA
    assert document["trend_baseline"]["state"] == "none"
    assert (document["result"], document["exit_code"]) == ("OK", 0)
    assert len(document["history"]) == 1
    walls = {wall["id"]: wall for wall in document["walls"]}
    assert {"release.census_bytes", "chunk_bytes.lines", "projection.expanded_bytes", "peak_rss.compiler"} <= set(walls)
    assert all(wall["status"] == "ok" for wall in walls.values())
    assert {group["group"] for group in document["field_census"]["groups"]} == {"graph_nodes", "lines"}
    assert "no baseline" in (tmp_path / "summary-11.md").read_text(encoding="utf-8")

    second = tmp_path / "second" / "capacity.json"
    arguments = _full_arguments(tmp_path, run_id="12", now="2026-10-11T00:00:00Z")
    assert capacity.main([*arguments, "--baseline", str(first), "--output", str(second)]) == capacity.EXIT_OK
    document = json.loads(second.read_text(encoding="utf-8"))
    assert document["trend_baseline"]["state"] == "loaded"
    assert [row["run_id"] for row in document["history"]] == ["11", "12"]
    walls = {wall["id"]: wall for wall in document["walls"]}
    assert walls["release.census_bytes"]["trend"]["delta"] == 0
    assert walls["release.census_bytes"]["trend"]["growth_per_day"] == pytest.approx(0.0)

    refused = tmp_path / "refused.json"
    refused.write_text("{not json", encoding="utf-8")
    third = tmp_path / "third" / "capacity.json"
    arguments = _full_arguments(tmp_path, run_id="13")
    assert capacity.main([*arguments, "--baseline", str(refused), "--output", str(third)]) == capacity.EXIT_OK
    assert json.loads(third.read_text(encoding="utf-8"))["trend_baseline"]["state"] == "refused"


def test_end_to_end_with_no_inputs_writes_the_record_and_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "capacity.json"
    code = capacity.main(["--output", str(output), "--summary", str(tmp_path / "summary.md"), "--now", "2026-10-10T00:00:00Z"])
    assert code == capacity.EXIT_INPUT
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["result"] == "FAIL (unmeasured input)"
    assert {wall["status"] for wall in document["walls"]} == {"unmeasured"}
    assert document["history"][0]["values"] == {}


def test_workflow_wires_the_guard_after_the_steps_it_reads() -> None:
    workflow = (MASTER_REFERENCE.parent / ".github" / "workflows" / "master-reference-ci.yml").read_text(
        encoding="utf-8"
    )
    guard = workflow.index("python -m cli.capacity")
    assert workflow.count("python -m cli.capacity") == 1
    for step in ("python -m cli build", "verify-family", "build/projection/build.mjs", "npm test"):
        assert workflow.index(step) < guard, step
    for report in ("compiler.time", "projection.time", "npm-test.time", "cli-build.time"):
        assert f'/usr/bin/time -v -o "$RUNNER_TEMP/atlas-capacity/{report}"' in workflow, report
        assert f'=$RUNNER_TEMP/atlas-capacity/{report}"' in workflow[guard:], report
    assert "if: ${{ !cancelled() }}" in workflow[workflow.rindex("- name:", 0, guard):guard]
    upload = workflow[workflow.index("actions/upload-artifact@"):]
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow[guard:]
    assert "name: master-reference-capacity" in upload
