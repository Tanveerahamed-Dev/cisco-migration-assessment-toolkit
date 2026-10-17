"""The full gate's verifier (.github/scripts/verify_shard_union.py): the required portable gate passes
only when the Python shards' evidence proves a selection cover (an exact, disjoint, non-empty cover of
one full collection), execution without failure (each shard executed exactly what it selected) and one
environment (each shard recorded the full collection's). Every refusal is exercised, each against a
case that differs from an accepted one in exactly that defect. The end-to-end runs with real pytest
shards are in tests/test_atlas_shard_partition.py.
"""
from __future__ import annotations

import importlib.util
import os
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
ENVIRONMENT = sorted(["python cpython 3.12.10 final", "pytest==9.1.1", "pyyaml==6.0.3", "setuptools==84.0.0"])


def _manifest(path: Path, rows) -> Path:
    path.write_bytes("".join(row + "\n" for row in rows).encode("utf-8"))
    return path


def _layout(tmp_path: Path, full=FULL, shards=SHARDS, executed=None, environments=None,
            full_environment=ENVIRONMENT) -> tuple[Path, Path, Path]:
    """``(full selection, full environment, evidence root)`` as the gate receives them: download-artifact
    gives every shard artifact its own directory, named after it. A shard executes what it selected
    and records the full environment unless ``executed`` / ``environments`` say otherwise."""
    root = tmp_path / "evidence"
    root.mkdir()
    for index, rows in enumerate(shards):
        directory = root / f"atlas-gate-shard-evidence-{index}"
        directory.mkdir()
        _manifest(directory / UNION.SELECTED, sorted(rows))
        _manifest(directory / UNION.EXECUTED, sorted(rows if executed is None else executed[index]))
        _manifest(directory / UNION.ENVIRONMENT,
                  sorted(full_environment if environments is None else environments[index]))
    return (_manifest(tmp_path / "full-selected.txt", sorted(full)),
            _manifest(tmp_path / "full-environment.txt", sorted(full_environment)), root)


def _main(full: Path, environment: Path, root: Path, expected: int = 2) -> int:
    return UNION.main(["--expected-shards", str(expected), "--full", str(full), "--environment", str(environment),
                       "--shard-dir", str(root)])


def _shard_dir(root: Path, index: int) -> Path:
    return root / f"atlas-gate-shard-evidence-{index}"


def _symlink_or_skip(link: Path, target: Path, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:  # Windows without the symlink privilege
        pytest.skip(f"this host cannot create a symbolic link: {error}")


# -- the accepted case ------------------------------------------------------------------------------

def test_an_exact_cover_executed_without_failure_in_one_environment_is_accepted(tmp_path, capsys):
    assert UNION.union_problems(FULL, SHARDS) == []
    full, environment, root = _layout(tmp_path)
    assert _main(full, environment, root) == 0
    out = capsys.readouterr().out
    assert "5 collected node ids = 2 + 3 across 2 disjoint shard(s)" in out
    assert "every shard executed its whole selection without failure" in out
    assert f"environment of {len(ENVIRONMENT)} row(s)" in out


# -- the selection cover ----------------------------------------------------------------------------

def test_the_union_is_counted_as_a_multiset_even_for_input_the_readers_would_refuse():
    """The pure check stays exact on repeated rows (which the command refuses before it gets here):
    a node id collected twice must be selected twice, in one shard."""
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


def test_a_union_refusal_names_the_shard_directory_it_is_about():
    assert UNION.union_problems(FULL, [[], FULL], ["evidence/atlas-gate-shard-evidence-0", "x"]) == [
        "shard manifest evidence/atlas-gate-shard-evidence-0 is empty"]


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
    full, environment, root = _layout(tmp_path, shards=shards)  # each shard executed what it selected
    assert _main(full, environment, root) == 1
    captured = capsys.readouterr()
    assert "shard union refused" in captured.err and "verified" not in captured.out


# -- execution without failure ----------------------------------------------------------------------

@pytest.mark.parametrize("executed,needle", [
    ([SHARDS[0], SHARDS[1][1:]],
     "atlas-gate-shard-evidence-1: 1 of its 3 selected node id(s) did not complete without failure: "
     "['tests/test_b.py::one']"),
    ([[], SHARDS[1]],
     "atlas-gate-shard-evidence-0: 2 of its 2 selected node id(s) did not complete without failure"),
    ([SHARDS[0] + ["tests/test_b.py::one"], SHARDS[1]],
     "atlas-gate-shard-evidence-0: 1 node id(s) completed that it did not select: ['tests/test_b.py::one']"),
], ids=["a-failed-test", "nothing-ran", "ran-unselected"])
def test_every_shard_must_execute_exactly_what_it_selected(tmp_path, capsys, executed, needle):
    full, environment, root = _layout(tmp_path, executed=executed)
    assert _main(full, environment, root) == 1
    err = capsys.readouterr().err
    assert needle in err, err
    assert "in no shard" not in err  # the selections themselves are a sound cover


# -- one environment --------------------------------------------------------------------------------

@pytest.mark.parametrize("shard_environment,needle", [
    ([row.replace("pytest==9.1.1", "pytest==9.1.2") for row in ENVIRONMENT],
     "1 row(s) only in the full collection ['pytest==9.1.1'], 1 only in the shard ['pytest==9.1.2']"),
    ([row for row in ENVIRONMENT if not row.startswith("pyyaml")],
     "1 row(s) only in the full collection ['pyyaml==6.0.3'], 0 only in the shard []"),
    (sorted(ENVIRONMENT + ["pyyaml==6.0.3"]), "0 row(s) only in the full collection [], 1 only in the shard"),
    ([row.replace("3.12.10", "3.12.9") for row in ENVIRONMENT], "only in the shard ['python cpython 3.12.9 final']"),
], ids=["another-version", "a-missing-distribution", "a-second-copy", "another-interpreter"])
def test_every_shard_must_record_the_full_collections_environment(tmp_path, capsys, shard_environment, needle):
    full, environment, root = _layout(tmp_path, environments=[ENVIRONMENT, shard_environment])
    assert _main(full, environment, root) == 1
    err = capsys.readouterr().err
    assert "atlas-gate-shard-evidence-1: its environment" in err and needle in err, err
    assert "atlas-gate-shard-evidence-0" not in err  # the other shard's environment is the full one


@pytest.mark.parametrize("full_environment,count", [
    ([row for row in ENVIRONMENT if not row.startswith("python ")], 0),
    (sorted(ENVIRONMENT + ["python cpython 3.13.1 final"]), 2),
    ([], 0),
], ids=["no-interpreter", "two-interpreters", "empty"])
def test_the_environment_must_record_exactly_one_interpreter(tmp_path, capsys, full_environment, count):
    """Even when every shard agrees with it: an environment that names no interpreter (or two) proves
    nothing about the one the shards ran on."""
    full, environment, root = _layout(tmp_path, full_environment=full_environment)
    assert _main(full, environment, root) == 1
    assert f"records {count} interpreter row(s), not exactly one" in capsys.readouterr().err


def test_a_repeated_environment_row_is_evidence_not_a_defect(tmp_path):
    """Two copies of one distribution on sys.path are two facts; every shard must record both."""
    repeated = sorted(ENVIRONMENT + ["pyyaml==6.0.3"])
    full, environment, root = _layout(tmp_path, full_environment=repeated)
    assert _main(full, environment, root) == 0


# -- the evidence layout ----------------------------------------------------------------------------

def test_the_shard_count_is_given_never_inferred(tmp_path, capsys):
    full, environment, root = _layout(tmp_path)
    assert _main(full, environment, root, expected=3) == 1  # a shard that never uploaded
    assert "expected exactly 3 shard evidence director(ies)" in capsys.readouterr().err
    third = _shard_dir(root, 2)
    third.mkdir()
    for name in UNION.SHARD_FILES:
        _manifest(third / name, [])
    assert _main(full, environment, root, expected=2) == 1  # evidence nobody ran for
    assert "expected exactly 2 shard evidence director(ies)" in capsys.readouterr().err


def test_a_single_artifact_downloaded_straight_into_the_root_is_refused(tmp_path, capsys):
    """download-artifact extracts a pattern that matches only ONE artifact directly into its path, not
    into a directory named after it: the three files then sit in the root, which is refused."""
    full, environment, root = _layout(tmp_path, shards=[FULL])
    only = _shard_dir(root, 0)
    for name in UNION.SHARD_FILES:
        os.replace(only / name, root / name)
    only.rmdir()
    assert _main(full, environment, root) == 1
    assert "not real shard evidence directories" in capsys.readouterr().err


@pytest.mark.parametrize("change", ["missing-selected", "missing-executed", "missing-environment",
                                    "extra-file", "extra-directory"])
def test_a_shard_directory_must_hold_exactly_the_three_evidence_files(tmp_path, capsys, change):
    full, environment, root = _layout(tmp_path)
    assert _main(full, environment, root) == 0  # the same layout, complete, is accepted
    capsys.readouterr()
    directory = _shard_dir(root, 1)
    if change.startswith("missing-"):
        (directory / f"{change.split('-', 1)[1]}.txt").unlink()
    elif change == "extra-file":
        _manifest(directory / "notes.txt", [])
    else:
        (directory / "nested").mkdir()
    assert _main(full, environment, root) == 1
    err = capsys.readouterr().err
    assert "atlas-gate-shard-evidence-1 must hold exactly" in err, err


def test_a_stray_file_in_the_evidence_root_is_refused(tmp_path, capsys):
    full, environment, root = _layout(tmp_path)
    _manifest(root / "atlas-gate-shard-evidence-2.txt", [])
    assert _main(full, environment, root) == 1
    assert "not real shard evidence directories: ['atlas-gate-shard-evidence-2.txt']" in capsys.readouterr().err


def test_a_linked_shard_directory_is_refused(tmp_path, capsys):
    full, environment, root = _layout(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    os.replace(_shard_dir(root, 1), elsewhere)
    _symlink_or_skip(_shard_dir(root, 1), elsewhere, directory=True)
    assert _main(full, environment, root) == 1
    assert "not real shard evidence directories: ['atlas-gate-shard-evidence-1']" in capsys.readouterr().err


def test_a_linked_evidence_file_is_refused(tmp_path, capsys):
    full, environment, root = _layout(tmp_path)
    selected = _shard_dir(root, 0) / UNION.SELECTED
    copy = tmp_path / "selected-copy.txt"
    os.replace(selected, copy)
    _symlink_or_skip(selected, copy)
    assert _main(full, environment, root) == 1
    assert f"holds entries that are not regular files: ['{UNION.SELECTED}']" in capsys.readouterr().err


# -- each manifest's bytes --------------------------------------------------------------------------

@pytest.mark.parametrize("data,needle", [
    (b"tests/test_a.py::one\r\ntests/test_a.py::two\r\n", "carriage return"),
    (b"tests/test_a.py::one\ntests/test_a.py::two", "line feed"),
    (b"tests/test_a.py::one\n\ntests/test_a.py::two\n", "blank row"),
    (b"tests/test_a.py::two\ntests/test_a.py::one\n", "not sorted"),
    (b"\xef\xbb\xbftests/test_a.py::one\ntests/test_a.py::two\n", "byte-order mark"),
    (b"tests/test_a.py::one\xff\ntests/test_a.py::two\n", "not UTF-8"),
], ids=["crlf", "unterminated", "blank", "unsorted", "bom", "not-utf8"])
@pytest.mark.parametrize("target", ["full", "full-environment", "selected", "executed", "environment"])
def test_a_malformed_manifest_is_refused_not_normalized(tmp_path, capsys, data, needle, target):
    full, environment, root = _layout(tmp_path)
    assert _main(full, environment, root) == 0  # the same layout, well formed, is accepted
    path = {"full": full, "full-environment": environment, "selected": _shard_dir(root, 0) / UNION.SELECTED,
            "executed": _shard_dir(root, 0) / UNION.EXECUTED,
            "environment": _shard_dir(root, 0) / UNION.ENVIRONMENT}[target]
    path.write_bytes(data)
    assert _main(full, environment, root) == 1
    assert needle in capsys.readouterr().err
    with pytest.raises(UNION.ManifestError, match=needle):
        UNION.read_manifest(str(path), unique=target not in ("full-environment", "environment"))


@pytest.mark.parametrize("target", ["full", "selected", "executed"])
def test_a_node_id_manifest_that_repeats_a_row_is_refused(tmp_path, capsys, target):
    """No node id manifest may repeat a row: a test collected, selected or executed twice under one id
    would let one run stand in for two."""
    full, environment, root = _layout(tmp_path)
    path = {"full": full, "selected": _shard_dir(root, 0) / UNION.SELECTED,
            "executed": _shard_dir(root, 0) / UNION.EXECUTED}[target]
    _manifest(path, sorted(UNION.read_manifest(str(path)) + ["tests/test_a.py::one"]))
    assert _main(full, environment, root) == 1
    assert "repeats 1 node id(s): ['tests/test_a.py::one']" in capsys.readouterr().err


def test_an_empty_file_is_an_empty_manifest(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert UNION.read_manifest(str(empty)) == []
    assert UNION.read_manifest(str(empty), unique=False) == []


def test_an_unreadable_input_is_a_refusal(tmp_path, capsys):
    full, environment, root = _layout(tmp_path)
    assert _main(tmp_path / "absent.txt", environment, root) == 1
    assert _main(full, tmp_path / "absent.txt", root) == 1
    assert _main(full, environment, tmp_path / "absent") == 1
    assert capsys.readouterr().err.count("shard union refused") == 3


@pytest.mark.parametrize("count", ["0", "-1", "02", "2.0", "two", ""])
def test_the_expected_shard_count_must_be_a_positive_integer(tmp_path, count):
    full, environment, root = _layout(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        UNION.main(["--expected-shards", count, "--full", str(full), "--environment", str(environment),
                    "--shard-dir", str(root)])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("dropped", ["--expected-shards", "--full", "--environment", "--shard-dir"])
def test_every_input_is_required(tmp_path, dropped):
    full, environment, root = _layout(tmp_path)
    arguments = {"--expected-shards": "2", "--full": str(full), "--environment": str(environment),
                 "--shard-dir": str(root)}
    del arguments[dropped]
    with pytest.raises(SystemExit) as excinfo:
        UNION.main([token for pair in arguments.items() for token in pair])
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
