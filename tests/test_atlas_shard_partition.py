"""The full gate's shard partition and evidence (tests/atlas_shard_partition.py) and the root
conftest.py hooks that apply them (`--atlas-shard I/N`, `--atlas-shard-manifest PATH`,
`--atlas-shard-executed PATH`, `--atlas-shard-environment PATH`).

The portable-release.yml `gate_shard` jobs each run one shard of the complete suite and the required
`gate` job proves, from their evidence, that the shards selected an exact disjoint cover of one full
collection, that each executed its whole selection without failure, and that all ran in that
collection's environment (.github/scripts/verify_shard_union.py, tests/test_verify_shard_union.py).
Here: the spec grammar, the partition's determinism, totality and disjointness, the manifest bytes,
the classification of test reports, the environment rows, the hooks' strict no-op without options,
their refusals, and -- end to end, in real pytest subprocesses -- that real shards and a real full
collection produce evidence the real verifier accepts, and that every kind of failing test (a failed
call, a setup or teardown error, a strict xpass, a failed subtest), a session ended early with a success
status, a ``--collect-only`` or ``--setup-plan`` shard and a dropped row are refused, including in the
gate's own invocation shape.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import atlas_shard_partition as shard
from pytest_invocation_reader import PYTEST_VALUE_OPTIONS

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / ".github" / "scripts" / "verify_shard_union.py"


def _load(name: str, path: Path):
    """A source file as its own module object (pytest registers the root conftest under a reused name)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT_CONFTEST = _load("_atlas_root_conftest_under_test", ROOT / "conftest.py")
#: The verifier owns the evidence layout (its file names), so the end-to-end runs below read it there.
UNION = _load("_atlas_shard_union_under_test", VERIFIER)


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


@pytest.mark.parametrize("option", ["--atlas-shard-manifest", "--atlas-shard-executed",
                                    "--atlas-shard-environment"])
def test_every_evidence_target_is_checked_and_named_by_its_option(tmp_path, option):
    existing = tmp_path / "existing.txt"
    existing.write_bytes(b"")
    with pytest.raises(shard.ShardOptionError, match=f"^{option} .*already exists"):
        shard.check_manifest_target(str(existing), option)
    with pytest.raises(shard.ShardOptionError, match=f"^{option} .*does not exist"):
        shard.check_manifest_target(str(tmp_path / "absent" / "x.txt"), option)
    shard.check_manifest_target(str(tmp_path / "new.txt"), option)  # a new file in a real directory


# -- which tests completed without failure ----------------------------------------------------------

_NODE = "tests/test_a.py::test_x"


#: The report shapes, synthetic. Which shape pytest itself gives each kind of test -- a strict xpass a
#: failed call, a plain xpass a passed one, a setup or teardown error, a failed subtest, a session ended
#: early -- is proven against REAL pytest runs below, never assumed here.
@pytest.mark.parametrize("phases,completed", [
    (("setup:passed", "call:passed", "teardown:passed"), True),
    (("setup:passed", "call:failed", "teardown:passed"), False),
    (("setup:failed", "teardown:passed"), False),
    (("setup:passed", "call:passed", "teardown:failed"), False),
    (("setup:skipped", "teardown:passed"), True),
    # an xfail is a skipped call
    (("setup:passed", "call:skipped", "teardown:passed"), True),
    (("setup:passed", "call:passed"), False),
    (("setup:passed", "teardown:passed"), False),
    (("teardown:passed",), False),
    # a failed subtest is one more call report under the test's own node id
    (("setup:passed", "call:failed", "call:passed", "teardown:passed"), False),
    (("setup:passed", "call:rerun", "setup:passed", "call:passed", "teardown:passed"), False),
    # the order reports arrive in does not matter
    (("teardown:passed", "call:passed", "setup:passed"), True),
], ids=["passed", "failed-call", "setup-error", "teardown-error", "skip-at-setup", "xfail", "no-teardown",
        "never-called", "teardown-only", "failed-subtest", "rerun-outcome", "any-order"])
def test_a_test_completed_without_failure_only_when_every_report_says_so(phases, completed):
    facts = [(_NODE, *phase.split(":")) for phase in phases]
    assert shard.completed_without_failure(facts) == ([_NODE] if completed else [])


def test_no_reports_complete_nothing_and_each_node_id_is_judged_alone():
    assert shard.completed_without_failure([]) == []
    facts = [("tests/test_b.py::ok", "setup", "passed"), ("tests/test_a.py::bad", "setup", "passed"),
             ("tests/test_a.py::ok", "setup", "skipped"), ("tests/test_b.py::ok", "call", "passed"),
             ("tests/test_a.py::bad", "call", "failed"), ("tests/test_a.py::ok", "teardown", "passed"),
             ("tests/test_b.py::ok", "teardown", "passed"), ("tests/test_a.py::bad", "teardown", "passed")]
    assert shard.completed_without_failure(facts) == ["tests/test_a.py::ok", "tests/test_b.py::ok"]
    assert shard.completed_without_failure(reversed(facts)) == ["tests/test_a.py::ok", "tests/test_b.py::ok"]


# -- the environment --------------------------------------------------------------------------------

def test_the_environment_is_the_interpreter_and_every_distribution_normalized_and_sorted():
    rows = shard.environment_rows(
        [("Zope.Interface", "7.2"), ("Foo_Bar.baz", "1.0"), ("foo--bar__baz", "1.0"), ("PyYAML", "6.0.3"),
         (None, None)],
        implementation="cpython", version_info=(3, 12, 10, "final", 0))
    assert rows == ["?==?", "foo-bar-baz==1.0", "foo-bar-baz==1.0", "python cpython 3.12.10 final",
                    "pyyaml==6.0.3", "zope-interface==7.2"]
    assert shard.manifest_text(rows) == "".join(row + "\n" for row in rows)  # already in manifest order
    assert shard.normalized_name("A--B__C..D-_.e") == "a-b-c-d-e"


def test_this_processs_environment_has_exactly_one_interpreter_row():
    rows = shard.environment_rows()
    assert rows == sorted(rows)
    assert [row for row in rows if row.startswith("python ")] == [
        shard.python_row(sys.implementation.name, sys.version_info)]
    assert all("==" in row for row in rows if not row.startswith("python "))
    assert "pytest==" + pytest.__version__ in rows  # the scan is live: it sees the running pytest


@pytest.mark.parametrize("distribution", [("bad\nname", "1.0"), ("good", "1.0\r"), ("good", "1.0\n2")])
def test_an_environment_row_that_is_not_one_line_is_refused(distribution):
    with pytest.raises(shard.ShardOptionError):
        shard.environment_rows([distribution], implementation="cpython", version_info=(3, 12, 10, "final"))


# -- the root conftest.py hooks, in process ---------------------------------------------------------

class _Config:
    """The few config members the hooks read, with the deselection hook and registrations recorded."""

    def __init__(self, spec=None, manifest=None, executed=None, environment=None, dist="no", worker=False):
        self.option = SimpleNamespace(atlas_shard=spec, atlas_shard_manifest=manifest,
                                      atlas_shard_executed=executed, atlas_shard_environment=environment,
                                      dist=dist)
        self.deselected: list = []
        self.registered: list = []
        self.hook = SimpleNamespace(pytest_deselected=lambda items: self.deselected.extend(items))
        self.pluginmanager = SimpleNamespace(
            register=lambda plugin, name=None: self.registered.append((name, plugin)))
        if worker:
            self.workerinput = {"workerid": "gw0"}

    def getoption(self, name, default=None):
        return getattr(self.option, name, default)


def _items():
    return [SimpleNamespace(nodeid=f"tests/test_{name}.py::case[{case}]") for name in "abcdefgh" for case in (1, 2)]


def test_without_any_option_the_hooks_change_nothing():
    """Even under xdist (the Stop hook's `-n auto`): without the options nothing is refused, and no
    recorder is registered either."""
    for config in (_Config(), _Config(dist="loadfile"), _Config(worker=True)):
        items = _items()
        before, alias = list(items), items
        assert ROOT_CONFTEST.pytest_configure(config) is None
        assert ROOT_CONFTEST.pytest_collection_modifyitems(None, config, items) is None
        assert items is alias and items == before and config.deselected == [] and config.registered == []


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
        assert config.registered == []  # no executed manifest was asked for
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


def test_the_environment_is_written_at_configure_before_any_test(tmp_path):
    target = tmp_path / "environment.txt"
    config = _Config(environment=str(target))
    ROOT_CONFTEST.pytest_configure(config)
    assert target.read_text(encoding="utf-8") == shard.manifest_text(shard.environment_rows())
    assert config.registered == []


def test_the_executed_recorder_writes_only_what_completed_without_failure(tmp_path):
    target = tmp_path / "executed.txt"
    config = _Config(spec="0/1", executed=str(target))
    ROOT_CONFTEST.pytest_configure(config)
    assert not target.exists()  # written when the session finishes, never before
    [(name, recorder)] = config.registered
    assert name == "atlas-shard-executed-recorder"
    for nodeid, when, outcome in [("tests/test_a.py::ok", "setup", "passed"), ("tests/test_a.py::ok", "call", "passed"),
                                  ("tests/test_a.py::bad", "setup", "passed"), ("tests/test_a.py::bad", "call", "failed"),
                                  ("tests/test_a.py::bad", "teardown", "passed"),
                                  ("tests/test_a.py::ok", "teardown", "passed"),
                                  ("tests/test_a.py::cut", "setup", "passed")]:
        recorder.pytest_runtest_logreport(SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome))
    session = SimpleNamespace(exitstatus=pytest.ExitCode.TESTS_FAILED)
    recorder.pytest_sessionfinish(session)
    assert target.read_bytes() == b"tests/test_a.py::ok\n"
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED  # the recorder never changes a verdict it may keep


def test_an_executed_manifest_that_cannot_be_written_fails_the_run(tmp_path, capsys):
    target = tmp_path / "executed.txt"
    config = _Config(executed=str(target))
    ROOT_CONFTEST.pytest_configure(config)
    [(_name, recorder)] = config.registered
    target.write_bytes(b"stale\n")  # appeared after the configure-time check
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    recorder.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.INTERNAL_ERROR
    assert target.read_bytes() == b"stale\n"
    assert "the executed manifest was not written" in capsys.readouterr().err


def test_the_recorder_and_the_modifyitems_hook_run_after_normally_ordered_implementations():
    """trylast: the selection is made after -k/-m deselection and fixture reordering, and a report is
    recorded after the implementations that may amend it. A later-registered trylast implementation
    or a wrapper still runs afterwards; that is what executed == selected in every shard catches."""
    assert ROOT_CONFTEST.pytest_collection_modifyitems.pytest_impl["trylast"] is True
    recorder = ROOT_CONFTEST._AtlasShardExecutedRecorder
    assert recorder.pytest_runtest_logreport.pytest_impl["trylast"] is True
    assert recorder.pytest_sessionfinish.pytest_impl["trylast"] is True


@pytest.mark.parametrize("config", [
    _Config(spec="2/2"), _Config(spec="0/2 "), _Config(spec="0/2", dist="load"),
    _Config(manifest="full.txt", dist="loadfile"), _Config(spec="0/2", worker=True),
    _Config(executed="executed.txt", dist="load"), _Config(environment="environment.txt", worker=True),
], ids=["index", "blank", "xdist", "xdist-manifest", "xdist-worker", "xdist-executed", "xdist-environment"])
def test_the_hooks_refuse_before_collection(config):
    with pytest.raises(pytest.UsageError):
        ROOT_CONFTEST.pytest_configure(config)
    assert config.registered == []


@pytest.mark.parametrize("field", ["manifest", "executed", "environment"])
def test_an_existing_or_unplaceable_evidence_file_is_refused_before_collection(tmp_path, field):
    stale = tmp_path / "stale.txt"
    stale.write_bytes(b"")
    with pytest.raises(pytest.UsageError, match="already exists"):
        ROOT_CONFTEST.pytest_configure(_Config(**{field: str(stale)}))
    with pytest.raises(pytest.UsageError, match="does not exist"):
        ROOT_CONFTEST.pytest_configure(_Config(**{field: str(tmp_path / "absent" / "x.txt")}))


def test_every_evidence_target_is_checked_before_any_evidence_is_written(tmp_path):
    stale, environment = tmp_path / "stale.txt", tmp_path / "environment.txt"
    stale.write_bytes(b"")
    config = _Config(manifest=str(stale), executed=str(tmp_path / "executed.txt"), environment=str(environment))
    with pytest.raises(pytest.UsageError, match="already exists"):
        ROOT_CONFTEST.pytest_configure(config)
    assert not environment.exists() and config.registered == []


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
    assert {"--atlas-shard", "--atlas-shard-manifest", "--atlas-shard-executed",
            "--atlas-shard-environment"} <= taking_value, taking_value  # the scan is live
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
#: Every project test file: passing tests, a test that skips in its call and an expected failure,
#: which pytest reports as a skipped call -- each of which completes without failure.
_PROJECT_TEST = """\
import pytest


def test_one():
    pass


@pytest.mark.parametrize("value", [1, 2])
def test_two(value):
    assert value


def test_skipped_in_its_call():
    pytest.skip("skips in the call")


@pytest.mark.xfail(reason="an expected failure", strict=True)
def test_expected_failure():
    assert False
"""
_PROJECT_CASES = ("test_one", "test_two[1]", "test_two[2]", "test_skipped_in_its_call", "test_expected_failure")
#: The gate-shaped project adds a skip marker, which pytest reports as a skipped SETUP.
_MARKER_SKIP_TEST = """\


@pytest.mark.skip(reason="a skip marker")
def test_skipped_by_a_marker():
    pass
"""
#: A file of every kind of failure, as pytest itself reports it: a failed call, a setup error, a
#: teardown error, a strict xfail that passes (a failed call) and, where pytest has subtests (9+), a
#: failed subtest -- beside a plain xfail that passes, which pytest counts as no failure.
_FAILING_TEST = """\
import pytest


@pytest.fixture
def setup_fails():
    raise RuntimeError("the fixture's setup fails")


@pytest.fixture
def teardown_fails():
    yield
    raise RuntimeError("the fixture's teardown fails")


def test_fails():
    assert False


def test_setup_fails(setup_fails):
    pass


def test_teardown_fails(teardown_fails):
    pass


@pytest.mark.xfail(reason="passes, which a strict xfail reports as a failure", strict=True)
def test_strict_xpass():
    pass


@pytest.mark.xfail(reason="passes, which a plain xfail allows", strict=False)
def test_plain_xpass():
    pass
"""
_FAILING_CASES = ("test_fails", "test_setup_fails", "test_teardown_fails", "test_strict_xpass")
_PASSING_CASES_OF_THE_FAILING_FILE = ("test_plain_xpass",)
#: A module-scoped fixture whose teardown fails: pytest reports that error on the teardown of the
#: module's LAST item, whatever that item did, so the first item completes and the last does not.
_MODULE_TEARDOWN_TEST = """\
import pytest


@pytest.fixture(scope="module")
def module_resource():
    yield
    raise RuntimeError("the module fixture's teardown fails")


def test_first_of_the_module(module_resource):
    pass


def test_last_of_the_module(module_resource):
    pass
"""
_FAILING_SUBTEST = """\


def test_a_subtest_fails(subtests):
    with subtests.test(msg="the failing subtest"):
        assert False
"""
_HAS_SUBTESTS = hasattr(pytest, "Subtests")


def _shard_files(directories: tuple[str, ...] = ("",)) -> dict[str, int]:
    """Three test file paths in each of two shards (rootdir-relative, as node ids spell them), each
    shard computed here from the spec's formula, independently of the helper. Every file name is
    unique across the directories: pytest's default import mode refuses two test modules of one name."""
    owners: dict[str, int] = {}
    for number in range(64):
        for directory in directories:
            path = f"{directory}/test_{directory}_{number:02d}.py" if directory else f"test_part_{number:02d}.py"
            owner = int(hashlib.sha256(path.encode("utf-8")).hexdigest(), 16) % 2
            if sum(1 for value in owners.values() if value == owner) < 3:
                owners[path] = owner
    assert sorted(owners.values()) == [0, 0, 0, 1, 1, 1], owners
    return owners


def _project(tmp_path: Path, *, directories: tuple[str, ...] = ("",), content: str = _PROJECT_TEST,
             ini: str = "[pytest]\n") -> tuple[Path, dict[str, int]]:
    """A throwaway pytest project wired to the REAL root conftest hooks, with files in both shards."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").write_text(ini, encoding="utf-8")
    (project / "conftest.py").write_text(
        _PROJECT_CONFTEST.format(conftest=str(ROOT / "conftest.py")), encoding="utf-8")
    owners = _shard_files(directories)
    for path in owners:
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(content, encoding="utf-8")
    return project, owners


def _expected(owners: dict[str, int], index: int | None = None, cases: tuple[str, ...] = _PROJECT_CASES) -> list[str]:
    return sorted(f"{path}::{case}" for path, owner in owners.items() if index is None or owner == index
                  for case in cases)


def _environment(addopts: str | None = None) -> dict[str, str]:
    # The outer run's own pytest controls (PYTEST_ADDOPTS, PYTEST_PLUGINS, an xdist worker's ids) stay
    # out; a scenario that needs PYTEST_ADDOPTS sets its own, explicitly.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTEST_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if addopts is not None:
        env["PYTEST_ADDOPTS"] = addopts
    return env


def _pytest(project: Path, *arguments: str, addopts: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(project / "pytest.ini"), "--rootdir", str(project),
         "-p", "no:cacheprovider", "-q", *arguments, str(project)],
        cwd=project, env=_environment(addopts), capture_output=True, text=True, timeout=300)


def _pytest_as_the_gate_runs_it(project: Path, *arguments: str) -> subprocess.CompletedProcess:
    """pytest in the gate's own invocation shape: from the project root with no ini, rootdir or path
    argument, so pytest finds the ini itself and collects its `testpaths` (the real gate's
    `tests webapp/tests`)."""
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *arguments],
                          cwd=project, env=_environment(), capture_output=True, text=True, timeout=300)


def _evidence(root: Path, index: int) -> SimpleNamespace:
    """One shard's evidence files, laid out as the gate's download receives them: one directory per
    shard artifact, named after the artifact."""
    directory = root / f"atlas-gate-shard-evidence-{index}"
    directory.mkdir(parents=True)
    return SimpleNamespace(directory=directory, selected=directory / UNION.SELECTED,
                           executed=directory / UNION.EXECUTED, environment=directory / UNION.ENVIRONMENT)


def _shard_arguments(evidence: SimpleNamespace, index: int) -> tuple[str, ...]:
    return ("--atlas-shard", f"{index}/2", "--atlas-shard-manifest", str(evidence.selected),
            "--atlas-shard-executed", str(evidence.executed),
            "--atlas-shard-environment", str(evidence.environment))


def _full_arguments(base: Path) -> tuple[str, ...]:
    return ("--collect-only", "--atlas-shard-manifest", str(base / "full-selected.txt"),
            "--atlas-shard-environment", str(base / "full-environment.txt"))


def _verify(base: Path, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERIFIER), "--expected-shards", "2",
                           "--full", str(base / "full-selected.txt"),
                           "--environment", str(base / "full-environment.txt"), "--shard-dir", str(root)],
                          capture_output=True, text=True, timeout=120)


def _rows(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _counts(output: str, **expected: int) -> bool:
    return all(re.search(rf"\b{count} {word}\b", output) for word, count in expected.items())


@pytest.fixture(scope="module")
def accepted(tmp_path_factory):
    """One project, both real shards run with every evidence option and the full collection with its
    environment: exactly the evidence the gate accepts. Read-only for the tests that use it."""
    base = tmp_path_factory.mktemp("accepted")
    project, owners = _project(base)
    root = base / "evidence"
    runs = []
    for index in range(2):
        evidence = _evidence(root, index)
        runs.append((evidence, _pytest(project, *_shard_arguments(evidence, index))))
    full = _pytest(project, *_full_arguments(base))
    return SimpleNamespace(base=base, project=project, owners=owners, root=root, runs=runs, full=full)


def _copy_of(accepted, tmp_path: Path) -> tuple[Path, Path]:
    """A private copy of the accepted inputs, so one test's mutation never reaches another."""
    for name in ("full-selected.txt", "full-environment.txt"):
        shutil.copyfile(accepted.base / name, tmp_path / name)
    shutil.copytree(accepted.root, tmp_path / "evidence")
    return tmp_path, tmp_path / "evidence"


def test_real_shards_and_a_full_collection_are_evidence_the_verifier_accepts(accepted):
    for index, (evidence, result) in enumerate(accepted.runs):
        assert result.returncode == 0, result.stdout + result.stderr
        assert _counts(result.stdout, passed=9, skipped=3, xfailed=3, deselected=15), result.stdout
        # every selected test completed without failure: the skips and the expected failures too
        assert _rows(evidence.selected) == _rows(evidence.executed) == _expected(accepted.owners, index)
        assert _rows(evidence.environment) == _rows(accepted.base / "full-environment.txt")
    assert accepted.full.returncode == 0, accepted.full.stdout + accepted.full.stderr
    assert _rows(accepted.base / "full-selected.txt") == _expected(accepted.owners)
    environment = _rows(accepted.base / "full-environment.txt")
    assert [row for row in environment if row.startswith("python ")] == [
        shard.python_row(sys.implementation.name, sys.version_info)]  # the same interpreter as this one
    assert "pytest==" + pytest.__version__ in environment

    verified = _verify(accepted.base, accepted.root)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "30 collected node ids = 15 + 15 across 2 disjoint shard(s)" in verified.stdout


def test_a_dropped_selection_row_is_refused(accepted, tmp_path):
    """The shape of a shard that silently lost a test."""
    base, root = _copy_of(accepted, tmp_path)
    selected = root / "atlas-gate-shard-evidence-0" / UNION.SELECTED
    rows = _rows(selected)
    selected.write_bytes("".join(row + "\n" for row in rows[1:]).encode("utf-8"))  # LF, on every OS
    refused = _verify(base, root)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "1 collected node id(s) are in no shard" in refused.stderr, refused.stderr


@pytest.mark.parametrize("addopts", ["--collect-only", "--setup-plan"])
def test_a_shard_that_runs_no_test_still_selects_them_and_is_refused(accepted, tmp_path, addopts):
    """P2 (a): PYTEST_ADDOPTS in a shard's environment keeps every selection green -- the manifest is
    written and pytest exits 0 -- while no test runs. The executed manifest records that nothing
    completed, and the verifier refuses the shard by name."""
    base, root = _copy_of(accepted, tmp_path)
    shutil.rmtree(root / "atlas-gate-shard-evidence-0")
    evidence = _evidence(root, 0)
    result = _pytest(accepted.project, *_shard_arguments(evidence, 0), addopts=addopts)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _rows(evidence.selected) == _expected(accepted.owners, 0)  # the selection alone looks complete
    assert evidence.executed.read_bytes() == b""
    assert _rows(evidence.environment) == _rows(base / "full-environment.txt")
    refused = _verify(base, root)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert ("atlas-gate-shard-evidence-0: 15 of its 15 selected node id(s) did not complete without failure"
            in refused.stderr), refused.stderr
    # the shard is refused for what it executed alone: its selection and environment are sound
    assert "in no shard" not in refused.stderr and "is not the full collection's" not in refused.stderr, (
        refused.stderr)


def _shard_zero_file(stem: str) -> str:
    """The first ``<stem>_NN.py`` whose SHA-256 residue puts it in shard 0 of 2 (computed here, from the
    spec's formula, independently of the helper)."""
    return next(f"{stem}_{number:02d}.py" for number in range(64)
                if int(hashlib.sha256(f"{stem}_{number:02d}.py".encode("utf-8")).hexdigest(), 16) % 2 == 0)


def _both_shards_and_the_full_collection(project: Path, base: Path) -> tuple[list, subprocess.CompletedProcess]:
    """Both real shards, each with every evidence option, and the real full collection."""
    root = base / "evidence"
    results = []
    for index in range(2):
        evidence = _evidence(root, index)
        results.append((evidence, _pytest(project, *_shard_arguments(evidence, index))))
    return results, _pytest(project, *_full_arguments(base))


def test_a_failing_test_is_missing_from_its_shards_executed_manifest_and_refused(tmp_path):
    """P2 (b)/(c): a failure whose exit status a step swallows still leaves the test out of the
    executed manifest, so the verifier refuses whatever the step's exit-code plumbing did -- for every
    kind of failure as REAL pytest reports it (a failed call, a setup error, a teardown error, a module
    fixture's teardown error on the module's last item, a strict xpass and a failed subtest), while a
    plain xpass, no failure to pytest, completes."""
    project, owners = _project(tmp_path)
    failing = _shard_zero_file("test_failing")
    (project / failing).write_text(_FAILING_TEST + (_FAILING_SUBTEST if _HAS_SUBTESTS else ""), encoding="utf-8")
    module = _shard_zero_file("test_module_teardown")
    (project / module).write_text(_MODULE_TEARDOWN_TEST, encoding="utf-8")
    failed = sorted([f"{failing}::{case}" for case in _FAILING_CASES] + [f"{module}::test_last_of_the_module"]
                    + ([f"{failing}::test_a_subtest_fails"] if _HAS_SUBTESTS else []))
    completed = sorted(_expected(owners, 0) + [f"{failing}::{case}" for case in _PASSING_CASES_OF_THE_FAILING_FILE]
                       + [f"{module}::test_first_of_the_module"])
    results, full = _both_shards_and_the_full_collection(project, tmp_path)
    assert full.returncode == 0, full.stdout + full.stderr

    (evidence_0, failed_run), (evidence_1, passed_run) = results
    assert failed_run.returncode == 1, failed_run.stdout + failed_run.stderr
    # pytest itself classified each case: three errors (a setup, a teardown, the module's teardown),
    # and the plain xpass as one
    assert _counts(failed_run.stdout, errors=3, xpassed=1), failed_run.stdout
    assert passed_run.returncode == 0, passed_run.stdout + passed_run.stderr
    assert _rows(evidence_0.selected) == sorted(completed + failed)
    assert _rows(evidence_0.executed) == completed  # everything but the failures completed
    assert _rows(evidence_1.selected) == _rows(evidence_1.executed) == _expected(owners, 1)
    refused = _verify(tmp_path, tmp_path / "evidence")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert (f"atlas-gate-shard-evidence-0: {len(failed)} of its {len(completed) + len(failed)} "
            f"selected node id(s) did not complete without failure: {failed}") in refused.stderr, refused.stderr


#: A file whose second test ends the whole session early WITH A SUCCESS STATUS.
_EXITING_TEST = """\
import pytest


def test_before_the_exit():
    pass


def test_exits():
    pytest.exit("ends the session early, with a success status", returncode=0)


def test_after_the_exit():
    pass
"""


def test_a_session_ended_early_with_a_success_status_is_refused(tmp_path):
    """``pytest.exit(returncode=0)`` mid-run exits 0, so every exit check passes; but the interrupted
    test logs no report after its setup and the tests after it never run, so they are missing from the
    executed manifest -- the shape of any run cut short behind a green exit status -- and refused."""
    project, owners = _project(tmp_path)
    exiting = _shard_zero_file("test_zexit")  # sorts after the "test_part" files, which all run first
    (project / exiting).write_text(_EXITING_TEST, encoding="utf-8")
    results, full = _both_shards_and_the_full_collection(project, tmp_path)
    assert full.returncode == 0, full.stdout + full.stderr

    (evidence_0, exited_run), (evidence_1, passed_run) = results
    assert exited_run.returncode == 0, exited_run.stdout + exited_run.stderr  # the status says success
    assert passed_run.returncode == 0, passed_run.stdout + passed_run.stderr
    cut = sorted(f"{exiting}::{case}" for case in ("test_exits", "test_after_the_exit"))
    completed = sorted(_expected(owners, 0) + [f"{exiting}::test_before_the_exit"])
    assert _rows(evidence_0.selected) == sorted(completed + cut)
    assert _rows(evidence_0.executed) == completed
    assert _rows(evidence_1.selected) == _rows(evidence_1.executed) == _expected(owners, 1)
    refused = _verify(tmp_path, tmp_path / "evidence")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert (f"atlas-gate-shard-evidence-0: {len(cut)} of its {len(completed) + len(cut)} selected node id(s) "
            f"did not complete without failure: {cut}") in refused.stderr, refused.stderr
    assert "in no shard" not in refused.stderr, refused.stderr  # its selection is sound; its run is not


def test_the_gates_own_invocation_shape_produces_evidence_the_verifier_accepts(tmp_path):
    """The gate runs pytest from the repository root with NO path argument, so pytest itself finds
    pytest.ini and collects its `testpaths`; the runs above pass -c, --rootdir and a path. Here the
    whole pipeline runs in the gate's shape: two `testpaths` directories, a decoy test outside them
    that only a run ignoring `testpaths` would collect, and a skip marker (a skipped setup)."""
    project, owners = _project(tmp_path, directories=("suite_a", "suite_b"), content=_PROJECT_TEST + _MARKER_SKIP_TEST,
                               ini="[pytest]\ntestpaths = suite_a suite_b\n")
    assert {path.split("/", 1)[0] for path in owners} == {"suite_a", "suite_b"}, owners
    (project / "decoy").mkdir()
    (project / "decoy" / "test_decoy.py").write_text("def test_decoy():\n    pass\n", encoding="utf-8")
    cases = _PROJECT_CASES + ("test_skipped_by_a_marker",)
    root = tmp_path / "evidence"
    for index in range(2):
        evidence = _evidence(root, index)
        result = _pytest_as_the_gate_runs_it(project, "--durations=40", *_shard_arguments(evidence, index))
        assert result.returncode == 0, result.stdout + result.stderr
        assert _counts(result.stdout, passed=9, skipped=6, xfailed=3, deselected=18), result.stdout
        assert _rows(evidence.selected) == _rows(evidence.executed) == _expected(owners, index, cases)
    full = _pytest_as_the_gate_runs_it(project, *_full_arguments(tmp_path))
    assert full.returncode == 0, full.stdout + full.stderr
    assert _rows(tmp_path / "full-selected.txt") == _expected(owners, None, cases)  # and no decoy
    verified = _verify(tmp_path, root)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "36 collected node ids = 18 + 18 across 2 disjoint shard(s)" in verified.stdout


def test_a_real_run_without_the_options_is_unsharded_and_writes_nothing(tmp_path):
    project, _owners = _project(tmp_path)
    before = sorted(path.name for path in tmp_path.rglob("*") if "__pycache__" not in path.parts)
    result = _pytest(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _counts(result.stdout, passed=18, skipped=6, xfailed=6) and "deselected" not in result.stdout, result.stdout
    assert sorted(path.name for path in tmp_path.rglob("*") if "__pycache__" not in path.parts) == before


@pytest.mark.parametrize("arguments,message", [
    (("--atlas-shard", "2/2"), "outside 0..1"),
    (("--atlas-shard", "1-of-2"), "must be I/N"),
    (("--atlas-shard-manifest", "{absent}"), "does not exist"),
    (("--atlas-shard-executed", "{existing}"), "already exists"),
    (("--atlas-shard-environment", "{absent}"), "does not exist"),
])
def test_a_real_run_with_a_bad_option_is_a_usage_error(tmp_path, arguments, message):
    project, _owners = _project(tmp_path)
    existing = tmp_path / "existing.txt"
    existing.write_bytes(b"")
    arguments = tuple(argument.format(absent=str(tmp_path / "absent" / "m.txt"), existing=str(existing))
                      for argument in arguments)
    result = _pytest(project, *arguments)
    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stderr, result.stderr
    assert existing.read_bytes() == b""
