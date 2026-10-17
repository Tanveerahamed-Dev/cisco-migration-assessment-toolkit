"""The full gate's union verifier (.github/scripts/verify_shard_union.py): the required portable gate
passes only when the Python shards' manifests are an exact, disjoint, non-empty cover of one full
collection. Every refusal is exercised, and each against a case that differs from an accepted one in
exactly that defect. The end-to-end run with real pytest shards is tests/test_atlas_shard_partition.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / ".github" / "scripts" / "verify_shard_union.py"


def _verifier_module():
    spec = importlib.util.spec_from_file_location("_verify_shard_union", VERIFIER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UNION = _verifier_module()

FULL = sorted(["tests/test_a.py::one", "tests/test_a.py::two", "tests/test_b.py::one",
               "webapp/tests/test_c.py::one[x]", "webapp/tests/test_c.py::one[y]"])
SHARDS = [["tests/test_a.py::one", "tests/test_a.py::two"],
          ["tests/test_b.py::one", "webapp/tests/test_c.py::one[x]", "webapp/tests/test_c.py::one[y]"]]


def _manifest(path: Path, rows) -> Path:
    path.write_bytes("".join(row + "\n" for row in rows).encode("utf-8"))
    return path


def _layout(tmp_path: Path, full=FULL, shards=SHARDS) -> tuple[Path, Path]:
    directory = tmp_path / "shards"
    directory.mkdir()
    for index, rows in enumerate(shards):
        _manifest(directory / f"shard-{index}.txt", sorted(rows))
    return _manifest(tmp_path / "full.txt", sorted(full)), directory


def _main(full: Path, directory: Path, expected: int = 2) -> int:
    return UNION.main(["--expected-shards", str(expected), "--full", str(full), "--shard-dir", str(directory)])


# -- the union --------------------------------------------------------------------------------------

def test_an_exact_disjoint_cover_is_accepted(tmp_path, capsys):
    assert UNION.union_problems(FULL, SHARDS) == []
    full, directory = _layout(tmp_path)
    assert _main(full, directory) == 0
    assert "5 collected node ids = 2 + 3 across 2 disjoint shard(s)" in capsys.readouterr().out


def test_a_duplicated_full_collection_row_is_accepted_only_with_the_same_multiplicity():
    """Exactness is a multiset: a node id pytest collected twice must run twice, in one shard."""
    full = sorted(FULL + ["tests/test_b.py::one"])
    assert UNION.union_problems(full, [SHARDS[0], sorted(SHARDS[1] + ["tests/test_b.py::one"])]) == []
    assert UNION.union_problems(full, SHARDS)  # one copy short


@pytest.mark.parametrize("shards,needle", [
    ([SHARDS[0], SHARDS[1][1:]], "1 collected node id(s) are in no shard: ['tests/test_b.py::one']"),
    ([SHARDS[0], SHARDS[1] + ["tests/test_z.py::invented"]],
     "1 shard node id(s) are not in the full collection: ['tests/test_z.py::invented']"),
    ([SHARDS[0] + ["tests/test_b.py::one"], SHARDS[1]],
     "1 node id(s) are in more than one shard: ['tests/test_b.py::one']"),
    ([SHARDS[0], SHARDS[1] + ["tests/test_b.py::one"]],
     "1 surplus duplicate shard row(s) beyond the full collection: ['tests/test_b.py::one']"),
    ([[], FULL], "shard manifest 0 is empty"),
    ([FULL, []], "shard manifest 1 is empty"),
    ([], "there are no shard manifests"),
], ids=["missing", "extra", "in-two-shards", "duplicate-in-one-shard", "empty-first", "empty-second", "none"])
def test_every_way_the_shards_fail_to_cover_the_collection_is_refused(shards, needle):
    problems = UNION.union_problems(FULL, shards)
    assert any(needle in problem for problem in problems), problems


def test_an_empty_full_collection_is_refused_even_with_empty_shards():
    assert "the full collection is empty" in UNION.union_problems([], [[], []])


def test_a_refusal_names_counts_and_a_bounded_sample():
    full = sorted(f"tests/test_{index:03d}.py::x" for index in range(40))
    problems = UNION.union_problems(full, [full[:1], full[1:2]])
    assert problems == [f"38 collected node id(s) are in no shard: {full[2:2 + UNION.SAMPLE]}"]


@pytest.mark.parametrize("mutation", ["missing", "extra", "in-two-shards", "empty"])
def test_the_command_exits_one_on_a_refused_union(tmp_path, capsys, mutation):
    shards = [list(SHARDS[0]), list(SHARDS[1])]
    if mutation == "missing":
        shards[1].remove("tests/test_b.py::one")
    elif mutation == "extra":
        shards[0].append("tests/test_a.py::three")
    elif mutation == "in-two-shards":
        shards[0].append("tests/test_b.py::one")
    else:
        shards = [[], FULL]
    full, directory = _layout(tmp_path, shards=shards)
    assert _main(full, directory) == 1
    captured = capsys.readouterr()
    assert "shard union refused" in captured.err and "verified" not in captured.out


# -- the manifest set and each manifest's bytes ------------------------------------------------------

def test_the_shard_count_is_given_never_inferred(tmp_path, capsys):
    full, directory = _layout(tmp_path)
    assert _main(full, directory, expected=3) == 1  # a shard that never uploaded
    assert "expected exactly 3 shard manifest(s)" in capsys.readouterr().err
    _manifest(directory / "shard-2.txt", ["tests/test_a.py::one"])
    assert _main(full, directory, expected=2) == 1  # a manifest nobody ran for
    assert "expected exactly 2 shard manifest(s)" in capsys.readouterr().err


def test_a_shard_directory_entry_that_is_not_a_regular_file_is_refused(tmp_path, capsys):
    full, directory = _layout(tmp_path, shards=[SHARDS[0], SHARDS[1]])
    (directory / "nested").mkdir()
    assert _main(full, directory, expected=3) == 1
    assert "not regular files" in capsys.readouterr().err


@pytest.mark.parametrize("data,needle", [
    (b"tests/test_a.py::one\r\ntests/test_a.py::two\r\n", "carriage return"),
    (b"tests/test_a.py::one\ntests/test_a.py::two", "line feed"),
    (b"tests/test_a.py::one\n\ntests/test_a.py::two\n", "blank row"),
    (b"tests/test_a.py::two\ntests/test_a.py::one\n", "not sorted"),
    (b"\xef\xbb\xbftests/test_a.py::one\ntests/test_a.py::two\n", "byte-order mark"),
    (b"tests/test_a.py::one\xff\ntests/test_a.py::two\n", "not UTF-8"),
], ids=["crlf", "unterminated", "blank", "unsorted", "bom", "not-utf8"])
def test_a_malformed_manifest_is_refused_not_normalized(tmp_path, capsys, data, needle):
    full, directory = _layout(tmp_path)
    assert _main(full, directory) == 0  # the same layout, well formed, is accepted
    (directory / "shard-0.txt").write_bytes(data)
    assert _main(full, directory) == 1
    assert needle in capsys.readouterr().err
    with pytest.raises(UNION.ManifestError, match=needle):
        UNION.read_manifest(str(directory / "shard-0.txt"))


def test_an_empty_file_is_an_empty_manifest(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert UNION.read_manifest(str(empty)) == []


def test_an_unreadable_input_is_a_refusal(tmp_path, capsys):
    full, directory = _layout(tmp_path)
    assert _main(tmp_path / "absent.txt", directory) == 1
    assert _main(full, tmp_path / "absent") == 1
    assert capsys.readouterr().err.count("shard union refused") == 2


@pytest.mark.parametrize("count", ["0", "-1", "02", "2.0", "two", ""])
def test_the_expected_shard_count_must_be_a_positive_integer(tmp_path, count):
    full, directory = _layout(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        UNION.main(["--expected-shards", count, "--full", str(full), "--shard-dir", str(directory)])
    assert excinfo.value.code == 2


def test_the_verifier_is_read_only_and_imports_no_repository_module():
    """It adds no static import edge to master-reference's release_distribution component, and writes
    nothing (so tests/client_artifact_census.py has no write site to classify)."""
    import ast

    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"))
    imported = {alias.name.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".", 1)[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported == {"__future__", "argparse", "collections", "os", "re", "sys"}, imported
    opened = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name) and node.func.id == "open"]
    assert opened and all(isinstance(node.args[1], ast.Constant) and node.args[1].value == "rb"
                          for node in opened)
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"write_text", "write_bytes", "write"}
                   for node in ast.walk(tree))
