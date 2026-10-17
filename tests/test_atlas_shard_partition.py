"""The full gate's shard partition (tests/atlas_shard_partition.py) and the root conftest.py hooks that
apply it (`--atlas-shard I/N`, `--atlas-shard-manifest PATH`).

The portable-release.yml `gate_shard` jobs each run one shard of the complete suite and the required
`gate` job proves their manifests are an exact disjoint cover of one full collection
(.github/scripts/verify_shard_union.py, tests/test_verify_shard_union.py). Here: the spec grammar,
the partition's determinism, totality and disjointness, the manifest bytes, the hooks' strict no-op
without options, their refusals, and -- end to end, in real pytest subprocesses -- that two shards
and a full collection produce manifests the real verifier accepts and a dropped row it refuses.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import atlas_shard_partition as shard
from pytest_invocation_reader import PYTEST_VALUE_OPTIONS

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / ".github" / "scripts" / "verify_shard_union.py"


def _root_conftest():
    """The root conftest.py as its own module object (pytest registers it under a reused name)."""
    spec = importlib.util.spec_from_file_location("_atlas_root_conftest_under_test", ROOT / "conftest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT_CONFTEST = _root_conftest()


# -- the spec ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("0/1", (0, 1)), ("0/2", (0, 2)), ("1/2", (1, 2)), ("9/10", (9, 10)), ("10/11", (10, 11)),
])
def test_a_well_formed_spec_parses(text, expected):
    assert shard.parse_spec(text) == expected


@pytest.mark.parametrize("text", [
    "", "2/2", "3/2", "0/0", "1/0", "-1/2", "+1/2", "01/2", "1/02", "1", "1/2/3", "a/b", "1 /2",
    " 1/2", "1/2 ", "1/2\n", "1/2\r", "１/２", "٠/٢", "0x1/2", "1.0/2", None, 1, b"0/2",
])
def test_every_malformed_spec_is_refused(text):
    with pytest.raises(shard.ShardOptionError):
        shard.parse_spec(text)


# -- the partition ----------------------------------------------------------------------------------

def test_the_shard_key_is_the_test_file():
    assert shard.file_key("tests/test_a.py::TestX::test_y[1::2]") == "tests/test_a.py"
    assert shard.file_key("webapp/tests/test_b.py") == "webapp/tests/test_b.py"


@pytest.mark.parametrize("path,total,expected", [
    # Pinned from SHA-256 digests computed outside Python (sha256sum): mod 2/4/16 is the last hex
    # digit's residue, and mod 3/5 the hex digit sum's, because 16 = 1 (mod 3) and (mod 5).
    ("tests/test_ssot_registry.py", 2, 0), ("tests/test_ssot_registry.py", 4, 2),
    ("tests/test_ssot_registry.py", 16, 10), ("tests/test_ssot_registry.py", 3, 0),
    ("tests/test_ssot_registry.py", 5, 0),
    ("webapp/tests/test_scope_mount.py", 2, 1), ("webapp/tests/test_scope_mount.py", 4, 1),
    ("webapp/tests/test_scope_mount.py", 16, 9), ("webapp/tests/test_scope_mount.py", 3, 1),
    ("webapp/tests/test_scope_mount.py", 5, 3),
    ("tests/test_portable_release_workflow.py", 2, 0), ("tests/test_atlas_shard_partition.py", 2, 1),
])
def test_a_file_shard_is_its_sha256_residue(path, total, expected):
    assert shard.shard_of(path, total) == expected
    assert shard.shard_of(path, 1) == 0


@pytest.mark.parametrize("total", [0, -1, True, 2.0, "2", None])
def test_a_shard_total_must_be_a_positive_integer(total):
    with pytest.raises(shard.ShardOptionError):
        shard.shard_of("tests/test_a.py", total)


def _real_test_files() -> list[str]:
    files = [path.relative_to(ROOT).as_posix()
             for directory in (ROOT / "tests", ROOT / "webapp" / "tests")
             for path in directory.rglob("test_*.py")]
    assert len(files) > 50, files  # the realistic denominator is live
    return sorted(files)


@pytest.mark.parametrize("total", [1, 2, 3, 4, 7])
def test_the_partition_of_the_real_test_files_is_total_and_disjoint(total):
    files = _real_test_files()
    buckets = [[path for path in files if shard.shard_of(path, total) == index] for index in range(total)]
    assert sorted(path for bucket in buckets for path in bucket) == files  # total, and nothing twice
    assert sum(len(bucket) for bucket in buckets) == len(files)
    assert all(buckets), [len(bucket) for bucket in buckets]  # no shard of the real suite is empty


def test_the_partition_does_not_depend_on_the_process_hash_seed():
    """``hash()`` is salted per process; the partition must not be. Two fresh interpreters with
    different PYTHONHASHSEED values assign every real test file exactly as this process does."""
    files = _real_test_files()
    expected = "".join(str(shard.shard_of(path, 3)) for path in files)
    program = ("import sys; sys.path.insert(0, sys.argv[1]); import atlas_shard_partition as s; "
               "print(''.join(str(s.shard_of(p, 3)) for p in sys.stdin.read().split()))")
    for seed in ("0", "4242"):
        result = subprocess.run([sys.executable, "-c", program, str(ROOT / "tests")], input=" ".join(files),
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "PYTHONHASHSEED": seed})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected, seed


def test_select_keeps_whole_files_in_their_original_order():
    nodeids = ["tests/test_a.py::one", "tests/test_b.py::one", "tests/test_a.py::two",
               "tests/test_c.py::one", "tests/test_b.py::two[x]", "tests/test_d.py::one"]
    items = [SimpleNamespace(nodeid=nodeid) for nodeid in nodeids]
    for index in range(2):
        kept, dropped = shard.select(items, index, 2)
        assert [item.nodeid for item in kept] == [n for n in nodeids if shard.shard_of(shard.file_key(n), 2) == index]
        assert [item.nodeid for item in dropped] == [n for n in nodeids if shard.shard_of(shard.file_key(n), 2) != index]
        kept_files = {shard.file_key(item.nodeid) for item in kept}
        assert not kept_files & {shard.file_key(item.nodeid) for item in dropped}


@pytest.mark.parametrize("index,total", [(2, 2), (-1, 2), (True, 2), (0, 0), (0, True)])
def test_select_refuses_an_index_outside_the_shards(index, total):
    with pytest.raises(shard.ShardOptionError):
        shard.select([SimpleNamespace(nodeid="tests/test_a.py::x")], index, total)


# -- the manifest -----------------------------------------------------------------------------------

def test_a_manifest_is_sorted_lf_terminated_utf8_rows(tmp_path):
    rows = ["tests/test_b.py::x", "tests/test_a.py::y[é]", "tests/test_a.py::x"]
    assert shard.manifest_text(rows) == "tests/test_a.py::x\ntests/test_a.py::y[é]\ntests/test_b.py::x\n"
    assert shard.manifest_text([]) == ""
    target = tmp_path / "selected.txt"
    shard.check_manifest_target(str(target))
    shard.write_manifest(str(target), rows)
    assert target.read_bytes() == shard.manifest_text(rows).encode("utf-8")
    assert b"\r" not in target.read_bytes()


@pytest.mark.parametrize("row", ["", "tests/test_a.py::x\n", "tests/test_a.py::x\r", None])
def test_a_row_that_is_not_one_line_is_refused(row):
    with pytest.raises(shard.ShardOptionError):
        shard.manifest_text(["tests/test_a.py::ok", row])


def test_a_manifest_is_written_once_never_over_an_existing_file(tmp_path):
    target = tmp_path / "selected.txt"
    target.write_bytes(b"stale\n")
    with pytest.raises(shard.ShardOptionError, match="already exists"):
        shard.check_manifest_target(str(target))
    with pytest.raises(FileExistsError):
        shard.write_manifest(str(target), ["tests/test_a.py::x"])
    assert target.read_bytes() == b"stale\n"
    with pytest.raises(shard.ShardOptionError, match="does not exist"):
        shard.check_manifest_target(str(tmp_path / "absent" / "selected.txt"))
    with pytest.raises(shard.ShardOptionError):
        shard.check_manifest_target("")


# -- the root conftest.py hooks, in process ---------------------------------------------------------

class _Config:
    """The few config members the hooks read, with the deselection hook recorded."""

    def __init__(self, spec=None, manifest=None, dist="no", worker=False):
        self.option = SimpleNamespace(atlas_shard=spec, atlas_shard_manifest=manifest, dist=dist)
        self.deselected: list = []
        self.hook = SimpleNamespace(pytest_deselected=lambda items: self.deselected.extend(items))
        if worker:
            self.workerinput = {"workerid": "gw0"}

    def getoption(self, name, default=None):
        return getattr(self.option, name, default)


def _items():
    return [SimpleNamespace(nodeid=f"tests/test_{name}.py::case[{case}]") for name in "abcdefgh" for case in (1, 2)]


def test_without_either_option_the_hooks_change_nothing():
    """Even under xdist (the Stop hook's `-n auto`): without the options nothing is refused either."""
    for config in (_Config(), _Config(dist="loadfile"), _Config(worker=True)):
        items = _items()
        before, alias = list(items), items
        assert ROOT_CONFTEST.pytest_configure(config) is None
        assert ROOT_CONFTEST.pytest_collection_modifyitems(None, config, items) is None
        assert items is alias and items == before and config.deselected == []


def test_a_shard_keeps_its_files_deselects_the_rest_and_records_what_remains(tmp_path):
    seen = []
    for index in range(2):
        items, manifest = _items(), tmp_path / f"shard-{index}.txt"
        config = _Config(spec=f"{index}/2", manifest=str(manifest))
        ROOT_CONFTEST.pytest_configure(config)
        everything = list(items)
        ROOT_CONFTEST.pytest_collection_modifyitems(None, config, items)
        assert items == [item for item in everything if shard.shard_of(shard.file_key(item.nodeid), 2) == index]
        assert config.deselected == [item for item in everything if item not in items]
        assert manifest.read_text(encoding="utf-8") == shard.manifest_text(item.nodeid for item in items)
        seen.append({item.nodeid for item in items})
    assert seen[0] and seen[1] and not seen[0] & seen[1]
    assert seen[0] | seen[1] == {item.nodeid for item in _items()}


def test_a_manifest_alone_records_the_full_collection(tmp_path):
    items, manifest = _items(), tmp_path / "full.txt"
    config = _Config(manifest=str(manifest))
    ROOT_CONFTEST.pytest_configure(config)
    ROOT_CONFTEST.pytest_collection_modifyitems(None, config, items)
    assert len(items) == 16 and config.deselected == []
    assert manifest.read_text(encoding="utf-8") == shard.manifest_text(item.nodeid for item in _items())


@pytest.mark.parametrize("config", [
    _Config(spec="2/2"), _Config(spec="0/2 "), _Config(spec="0/2", dist="load"),
    _Config(manifest="full.txt", dist="loadfile"), _Config(spec="0/2", worker=True),
], ids=["index", "blank", "xdist", "xdist-manifest", "xdist-worker"])
def test_the_hooks_refuse_before_collection(config):
    with pytest.raises(pytest.UsageError):
        ROOT_CONFTEST.pytest_configure(config)


def test_an_existing_manifest_is_refused_before_collection(tmp_path):
    stale = tmp_path / "full.txt"
    stale.write_bytes(b"")
    with pytest.raises(pytest.UsageError, match="already exists"):
        ROOT_CONFTEST.pytest_configure(_Config(manifest=str(stale)))


def test_the_modifyitems_hook_runs_last():
    """It must see the item set every other plugin's modifyitems left (-k/-m, fixture reordering)."""
    assert ROOT_CONFTEST.pytest_collection_modifyitems.pytest_impl["trylast"] is True


def test_every_value_option_the_root_conftest_adds_is_known_to_the_invocation_reader():
    """A conftest option that takes a value, unknown to tests/pytest_invocation_reader.py, would make
    the reader read its value as a collected path -- and a full-suite CI leg would drop out of every
    leg guard (fetch-depth, /scope pins). Derived from conftest.py's own addoption calls."""
    tree = ast.parse((ROOT / "conftest.py").read_text(encoding="utf-8"))
    taking_value = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "addoption":
            action = next((keyword.value.value for keyword in node.keywords if keyword.arg == "action"
                           and isinstance(keyword.value, ast.Constant)), "store")
            if action in ("store", "append"):
                taking_value.update(arg.value for arg in node.args if isinstance(arg, ast.Constant))
    assert {"--atlas-shard", "--atlas-shard-manifest"} <= taking_value, taking_value  # the scan is live
    assert taking_value <= PYTEST_VALUE_OPTIONS, sorted(taking_value - PYTEST_VALUE_OPTIONS)


# -- end to end: real pytest processes, the real conftest hooks, the real verifier -----------------

_PROJECT_CONFTEST = """\
import importlib.util

_spec = importlib.util.spec_from_file_location("_atlas_root_conftest", {conftest!r})
_root = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root)
pytest_addoption = _root.pytest_addoption
pytest_configure = _root.pytest_configure
pytest_collection_modifyitems = _root.pytest_collection_modifyitems
"""
_PROJECT_TEST = """\
import pytest


def test_one():
    pass


@pytest.mark.parametrize("value", [1, 2])
def test_two(value):
    assert value
"""


def _project(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    """A throwaway pytest project wired to the REAL root conftest hooks, with files in both shards.
    Each file's shard is computed here from the spec's formula, independently of the helper."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project / "conftest.py").write_text(
        _PROJECT_CONFTEST.format(conftest=str(ROOT / "conftest.py")), encoding="utf-8")
    owners: dict[str, int] = {}
    for number in range(64):
        name = f"test_part_{number:02d}.py"
        owner = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % 2
        if sum(1 for value in owners.values() if value == owner) < 3:
            owners[name] = owner
            (project / name).write_text(_PROJECT_TEST, encoding="utf-8")
        if len(owners) == 6:
            break
    assert sorted(owners.values()) == [0, 0, 0, 1, 1, 1], owners
    return project, owners


def _pytest(project: Path, *arguments: str) -> subprocess.CompletedProcess:
    # The outer run's own pytest controls (PYTEST_ADDOPTS, PYTEST_PLUGINS, an xdist worker's ids) stay out.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTEST_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(project / "pytest.ini"), "--rootdir", str(project),
         "-p", "no:cacheprovider", "-q", *arguments, str(project)],
        cwd=project, env=env, capture_output=True, text=True, timeout=300)


def _expected(owners: dict[str, int], index: int | None = None) -> list[str]:
    return sorted(f"{name}::{case}" for name, owner in owners.items() if index is None or owner == index
                  for case in ("test_one", "test_two[1]", "test_two[2]"))


def test_two_real_shards_and_a_full_collection_are_an_exact_cover_the_verifier_accepts(tmp_path):
    project, owners = _project(tmp_path)
    shards, full = tmp_path / "shards", tmp_path / "full.txt"
    shards.mkdir()
    for index in range(2):
        manifest = shards / f"shard-{index}.txt"
        result = _pytest(project, "--atlas-shard", f"{index}/2", "--atlas-shard-manifest", str(manifest))
        assert result.returncode == 0, result.stdout + result.stderr
        assert re.search(r"\b9 passed, 9 deselected\b", result.stdout), result.stdout
        assert manifest.read_text(encoding="utf-8").splitlines() == _expected(owners, index)
    result = _pytest(project, "--collect-only", "--atlas-shard-manifest", str(full))
    assert result.returncode == 0, result.stdout + result.stderr
    assert full.read_text(encoding="utf-8").splitlines() == _expected(owners)

    verified = subprocess.run([sys.executable, str(VERIFIER), "--expected-shards", "2", "--full", str(full),
                               "--shard-dir", str(shards)], capture_output=True, text=True, timeout=120)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "18 collected node ids = 9 + 9 across 2 disjoint shard(s)" in verified.stdout

    # one dropped row -- the shape of a shard that silently lost a test -- is refused
    shard_zero = shards / "shard-0.txt"
    rows = shard_zero.read_text(encoding="utf-8").splitlines()
    shard_zero.write_bytes("".join(row + "\n" for row in rows[1:]).encode("utf-8"))  # LF, on every OS
    refused = subprocess.run([sys.executable, str(VERIFIER), "--expected-shards", "2", "--full", str(full),
                              "--shard-dir", str(shards)], capture_output=True, text=True, timeout=120)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "1 collected node id(s) are in no shard" in refused.stderr, refused.stderr


def test_a_real_run_without_the_options_is_unsharded_and_writes_nothing(tmp_path):
    project, _owners = _project(tmp_path)
    before = sorted(path.name for path in tmp_path.rglob("*") if "__pycache__" not in path.parts)
    result = _pytest(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b18 passed\b", result.stdout) and "deselected" not in result.stdout, result.stdout
    assert sorted(path.name for path in tmp_path.rglob("*") if "__pycache__" not in path.parts) == before


@pytest.mark.parametrize("arguments,message", [
    (("--atlas-shard", "2/2"), "outside 0..1"),
    (("--atlas-shard", "1-of-2"), "must be I/N"),
    (("--atlas-shard-manifest", "{absent}"), "does not exist"),
])
def test_a_real_run_with_a_bad_option_is_a_usage_error(tmp_path, arguments, message):
    project, _owners = _project(tmp_path)
    arguments = tuple(argument.format(absent=str(tmp_path / "absent" / "m.txt")) for argument in arguments)
    result = _pytest(project, *arguments)
    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stderr, result.stderr
