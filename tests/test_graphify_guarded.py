"""Executable contract for the narrow Graphify 0.9.51 producer overlays."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import inspect
import json
import os
import shutil
import subprocess
import sys
import types
from contextlib import nullcontext
from pathlib import Path, PurePosixPath

import pytest

from tools import graphify_guarded as guard

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 12), reason="guard runtime requires Python 3.12+"
)

_REAL_PRODUCER_ROOT = guard._producer_root
_REAL_PRODUCER_LOCK = guard._producer_lock


@pytest.fixture(autouse=True)
def _isolated_invocation_contract(monkeypatch):
    """Unit calls model the required ``python -I -B`` process boundary."""

    monkeypatch.setattr(guard, "_invocation_isolated", lambda: True)
    monkeypatch.setattr(guard, "_producer_root", lambda _arguments: Path.cwd().resolve())
    monkeypatch.setattr(guard, "_producer_lock", lambda _root: nullcontext())


def _reviewed_install_available() -> bool:
    try:
        distribution = metadata.distribution(guard.DIST_NAME)
        if distribution.version != guard.EXPECTED_VERSION:
            return False
        sources = {}
        for relative_path in (
            guard.EXTRACTOR_RELATIVE_PATH,
            guard.REPORT_RELATIVE_PATH,
            guard.WATCH_RELATIVE_PATH,
        ):
            matches = [
                item
                for item in (distribution.files or ())
                if str(item).replace("\\", "/") == relative_path
            ]
            if len(matches) != 1:
                return False
            sources[relative_path] = Path(distribution.locate_file(matches[0])).read_bytes()
    except (metadata.PackageNotFoundError, OSError, TypeError, ValueError):
        return False
    return (
        hashlib.sha256(sources[guard.EXTRACTOR_RELATIVE_PATH]).hexdigest()
        == guard.EXPECTED_SOURCE_SHA256
        and hashlib.sha256(sources[guard.REPORT_RELATIVE_PATH]).hexdigest()
        == guard.EXPECTED_REPORT_SOURCE_SHA256
        and hashlib.sha256(sources[guard.WATCH_RELATIVE_PATH]).hexdigest()
        == guard.EXPECTED_WATCH_SOURCE_SHA256
    )


class _Distribution:
    def __init__(self, root: Path, *, version: str = guard.EXPECTED_VERSION) -> None:
        self.root = root
        self.version = version
        self.files = [
            PurePosixPath(guard.EXTRACTOR_RELATIVE_PATH),
            PurePosixPath(guard.REPORT_RELATIVE_PATH),
            PurePosixPath(guard.WATCH_RELATIVE_PATH),
        ]

    def locate_file(self, relative: PurePosixPath) -> Path:
        return self.root / Path(*relative.parts)


def _synthetic_source() -> bytes:
    return (
        b"def extract_json(val, key):\n"
        b"    if True:\n"
        b"        if True:\n"
        b"            if False:\n"
        b"                return 'never'\n"
        b'            elif val.type == "array":\n'
        b"                return 'array'\n"
        b"    return 'other'\n"
    )


def _configure_synthetic_hashes(monkeypatch, source: bytes) -> bytes:
    patched = source.replace(guard._SOURCE_SENTINEL, guard._PATCHED_SENTINEL, 1)
    monkeypatch.setattr(guard, "EXPECTED_SOURCE_BYTES", len(source))
    monkeypatch.setattr(guard, "EXPECTED_SOURCE_SHA256", hashlib.sha256(source).hexdigest())
    monkeypatch.setattr(guard, "EXPECTED_PATCHED_BYTES", len(patched))
    monkeypatch.setattr(guard, "EXPECTED_PATCHED_SHA256", hashlib.sha256(patched).hexdigest())
    return patched


def _synthetic_report_source() -> bytes:
    return (
        b"def generate(communities, non_empty, thin_count_summary):\n"
        b"    shown_count = len(communities) - thin_count_summary\n"
        b"    return shown_count\n"
    )


def _configure_synthetic_report_hashes(monkeypatch, source: bytes) -> bytes:
    patched = source.replace(
        guard._REPORT_SOURCE_SENTINEL,
        guard._REPORT_PATCHED_SENTINEL,
        1,
    )
    monkeypatch.setattr(guard, "EXPECTED_REPORT_SOURCE_BYTES", len(source))
    monkeypatch.setattr(
        guard,
        "EXPECTED_REPORT_SOURCE_SHA256",
        hashlib.sha256(source).hexdigest(),
    )
    monkeypatch.setattr(guard, "EXPECTED_REPORT_PATCHED_BYTES", len(patched))
    monkeypatch.setattr(
        guard,
        "EXPECTED_REPORT_PATCHED_SHA256",
        hashlib.sha256(patched).hexdigest(),
    )
    return patched


def _synthetic_watch_source() -> bytes:
    return (
        b"def _rebuild_code(existing_graph_data, same_graph=True, same_report=True):\n"
        b"    try:\n"
        b"        commit = _git_head(cwd=watch_root)\n"
        b"        result = extract(\n"
        b"        )\n"
        b"        candidate_topology = _topology_from_graph(G)\n"
        b"        if existing_graph_data:\n"
        b"            same_topology = True\n"
        b"            if same_topology:\n"
        b"                return 'fast-noop'\n"
        b"        no_change = same_graph and same_report\n"
        b"        if no_change:\n"
        b"            return 'late-noop'\n"
        b"        return 'rebuilt'\n"
        b"    finally:\n"
        b"        pass\n"
    )


def _configure_synthetic_watch_hashes(monkeypatch, source: bytes) -> bytes:
    patched = source.replace(
        guard._REBUILD_COMMIT_SOURCE_SENTINEL,
        guard._REBUILD_COMMIT_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        guard._REBUILD_TOPOLOGY_SOURCE_SENTINEL,
        guard._REBUILD_TOPOLOGY_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        guard._REBUILD_FAST_SOURCE_SENTINEL,
        guard._REBUILD_FAST_PATCHED_SENTINEL,
        1,
    )
    patched = patched.replace(
        guard._REBUILD_FINAL_SOURCE_SENTINEL,
        guard._REBUILD_FINAL_PATCHED_SENTINEL,
        1,
    )
    monkeypatch.setattr(guard, "EXPECTED_WATCH_SOURCE_BYTES", len(source))
    monkeypatch.setattr(
        guard,
        "EXPECTED_WATCH_SOURCE_SHA256",
        hashlib.sha256(source).hexdigest(),
    )
    monkeypatch.setattr(guard, "EXPECTED_REBUILD_SOURCE_BYTES", len(source))
    monkeypatch.setattr(
        guard,
        "EXPECTED_REBUILD_SOURCE_SHA256",
        hashlib.sha256(source).hexdigest(),
    )
    monkeypatch.setattr(guard, "EXPECTED_REBUILD_PATCHED_BYTES", len(patched))
    monkeypatch.setattr(
        guard,
        "EXPECTED_REBUILD_PATCHED_SHA256",
        hashlib.sha256(patched).hexdigest(),
    )
    return patched


def _overlay_harness(tmp_path, monkeypatch):
    source = _synthetic_source()
    _configure_synthetic_hashes(monkeypatch, source)
    report_source = _synthetic_report_source()
    _configure_synthetic_report_hashes(monkeypatch, report_source)
    watch_source = _synthetic_watch_source()
    _configure_synthetic_watch_hashes(monkeypatch, watch_source)
    source_path = tmp_path / Path(*guard.EXTRACTOR_RELATIVE_PATH.split("/"))
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    report_source_path = tmp_path / Path(*guard.REPORT_RELATIVE_PATH.split("/"))
    report_source_path.parent.mkdir(parents=True, exist_ok=True)
    report_source_path.write_bytes(report_source)
    watch_source_path = tmp_path / Path(*guard.WATCH_RELATIVE_PATH.split("/"))
    watch_source_path.parent.mkdir(parents=True, exist_ok=True)
    watch_source_path.write_bytes(watch_source)

    original = types.ModuleType(guard.EXTRACTOR_MODULE)
    original.__file__ = str(source_path)
    original_extract_json = lambda _path: "original"  # noqa: E731
    original.extract_json = original_extract_json

    extractors = types.ModuleType("graphify.extractors")
    extractors.json_config = original
    extractors.extract_json = original_extract_json
    extractors.LANGUAGE_EXTRACTORS = {"json": original_extract_json}

    facade = types.ModuleType("graphify.extract")
    facade.extract_json = original_extract_json
    facade._DISPATCH = {".json": original_extract_json}
    facade._JS_CACHE_BYPASS_SUFFIXES = {".js"}

    models = types.ModuleType("graphify.extractors.models")
    models._JS_CACHE_BYPASS_SUFFIXES = facade._JS_CACHE_BYPASS_SUFFIXES

    report = types.ModuleType(guard.REPORT_MODULE)
    report.__file__ = str(report_source_path)
    original_generate = lambda *_args: "original"  # noqa: E731
    report.generate = original_generate

    watch = types.ModuleType(guard.WATCH_MODULE)
    watch.__file__ = str(watch_source_path)
    exec(compile(watch_source.decode("utf-8"), str(watch_source_path), "exec"), watch.__dict__)
    watch._head = "same"
    watch._extract_calls = []
    watch._unlink_calls = []
    watch._git_head = lambda **_kwargs: watch._head
    watch.watch_root = tmp_path
    watch.extract = lambda: watch._extract_calls.append(True) or {}
    watch.G = {}
    watch._topology_from_graph = lambda _result: {}
    watch.graph_tmp = types.SimpleNamespace(
        unlink=lambda **kwargs: watch._unlink_calls.append(kwargs)
    )
    watch.re = __import__("re")
    watch.sys = sys

    graphify_package = types.ModuleType("graphify")
    graphify_package.report = report

    modules = {
        guard.EXTRACTOR_MODULE: original,
        "graphify.extractors": extractors,
        "graphify.extractors.models": models,
        "graphify.extract": facade,
        "graphify": graphify_package,
        guard.REPORT_MODULE: report,
        guard.WATCH_MODULE: watch,
    }
    monkeypatch.setitem(sys.modules, guard.EXTRACTOR_MODULE, original)

    distribution = _Distribution(tmp_path)

    def get_distribution(name):
        assert name == guard.DIST_NAME
        return distribution

    def import_module(name):
        return modules[name]

    return (
        source_path,
        source,
        report_source_path,
        report_source,
        extractors,
        facade,
        graphify_package,
        report,
        get_distribution,
        import_module,
    )


def test_reviewed_graphify_identity_constants_are_exact():
    assert guard.DIST_NAME == "graphifyy"
    assert guard.EXPECTED_VERSION == "0.9.51"
    assert guard.GUARD_CONTRACT == "graphify-producer-overlays/4"
    assert guard.EXTRACTOR_RELATIVE_PATH == "graphify/extractors/json_config.py"
    assert guard.EXPECTED_SOURCE_BYTES == 9_723
    assert guard.EXPECTED_SOURCE_SHA256 == (
        "d15ea6d9b48cc71e73615c44c72808562ad4a1dbc82d5a340e3ad0c2fb4fc945"
    )
    assert guard.EXPECTED_PATCHED_BYTES == 9_744
    assert guard.EXPECTED_PATCHED_SHA256 == (
        "cb6b660bd2dee3f58e9007d0eac27883cd3bb3fe5d8136c13e8d83b92b90e011"
    )
    assert guard.REPORT_RELATIVE_PATH == "graphify/report.py"
    assert guard.EXPECTED_REPORT_SOURCE_BYTES == 14_395
    assert guard.EXPECTED_REPORT_SOURCE_SHA256 == (
        "382d844327181b652bbcd3ebd9cc3f2ab63bbce30e6eb5da80ced2b1575d1d0a"
    )
    assert guard.EXPECTED_REPORT_PATCHED_BYTES == 14_393
    assert guard.EXPECTED_REPORT_PATCHED_SHA256 == (
        "b6855a4111f7aec351022fc0d7ed96359216eb3b48c307ea025b8b41ef600bb9"
    )
    assert guard.WATCH_RELATIVE_PATH == "graphify/watch.py"
    assert guard.EXPECTED_WATCH_SOURCE_BYTES == 95_869
    assert guard.EXPECTED_WATCH_SOURCE_SHA256 == (
        "664547629cb659f3b0fa7209f8461acfd1b96985caf87944591dadb0c9f0e93d"
    )
    assert guard.EXPECTED_REBUILD_SOURCE_BYTES == 42_104
    assert guard.EXPECTED_REBUILD_SOURCE_SHA256 == (
        "4c1283138dfb003bf7cd768c2ba6fb94d2ae6869d0d8b4ac42cc54253163be18"
    )
    assert guard.EXPECTED_REBUILD_PATCHED_BYTES == 42_925
    assert guard.EXPECTED_REBUILD_PATCHED_SHA256 == (
        "1858a57219a040f145804893816d6f0fd61c796e0876110b2aaeda408cba4782"
    )
    assert guard.WORKER_ENV == "GRAPHIFY_MAX_WORKERS"
    assert guard.GUARDED_MAX_WORKERS == "1"
    assert guard._JSON_SUFFIX_VARIANTS == {
        ".json", ".Json", ".jSon", ".JSon", ".jsOn", ".JsOn", ".jSOn", ".JSOn",
        ".jsoN", ".JsoN", ".jSoN", ".JSoN", ".jsON", ".JsON", ".jSON", ".JSON",
    }


@pytest.mark.skipif(
    not _reviewed_install_available(),
    reason="the exact official Graphifyy 0.9.51 extractor, reporter, and rebuild are not installed",
)
def test_real_probe_identity_exactly_matches_selfcheck_owner():
    from cisco_toolkit import selfcheck

    root = Path(guard.__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(guard.__file__).resolve()), "--probe"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    probe = json.loads(completed.stdout)
    probe.pop("python")
    assert probe == selfcheck.GRAPHIFY_GUARD_IDENTITY


@pytest.mark.parametrize(
    "relative",
    [
        "cisco_toolkit/selfcheck.py",
        ".claude/fullpower-max-default.md",
        ".claude/commands/fullpower.md",
        ".claude/commands/fullpower-max.md",
    ],
)
def test_active_refresh_runbooks_route_through_the_guard(relative):
    root = Path(guard.__file__).resolve().parents[1]
    text = (root / relative).read_text(encoding="utf-8")
    assert "py -3.12 -I -B tools/graphify_guarded.py update ." in text
    assert "python -m graphify update ." not in text
    assert "`graphify update .`" not in text


def test_verified_patch_is_exact_and_does_not_modify_installed_source(tmp_path, monkeypatch):
    source = _synthetic_source()
    expected = _configure_synthetic_hashes(monkeypatch, source)
    installed = tmp_path / "json_config.py"
    installed.write_bytes(source)

    patched = guard._verified_patch(guard._read_stable_source(installed))

    assert patched == expected
    assert installed.read_bytes() == source
    assert guard._SOURCE_SENTINEL not in patched
    assert patched.count(guard._PATCHED_SENTINEL) == 1


@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda payload: payload + b"# drift\n", "G004"),
        (lambda payload: payload.replace(guard._SOURCE_SENTINEL, b"# missing"), "G004"),
        (lambda payload: payload.replace(
            guard._SOURCE_SENTINEL,
            guard._SOURCE_SENTINEL + b"\n" + guard._SOURCE_SENTINEL,
        ), "G004"),
    ],
)
def test_verified_patch_rejects_source_drift(monkeypatch, mutator, code):
    source = _synthetic_source()
    _configure_synthetic_hashes(monkeypatch, source)
    with pytest.raises(guard.GuardFailure, match=code):
        guard._verified_patch(mutator(source))


def test_verified_patch_rejects_an_unreviewed_result(monkeypatch):
    source = _synthetic_source()
    _configure_synthetic_hashes(monkeypatch, source)
    monkeypatch.setattr(guard, "EXPECTED_PATCHED_SHA256", "0" * 64)
    with pytest.raises(guard.GuardFailure, match="G005"):
        guard._verified_patch(source)


def test_verified_report_patch_is_exact_and_does_not_modify_installed_source(
    tmp_path, monkeypatch
):
    source = _synthetic_report_source()
    expected = _configure_synthetic_report_hashes(monkeypatch, source)
    installed = tmp_path / "report.py"
    installed.write_bytes(source)

    patched = guard._verified_report_patch(guard._read_stable_source(installed))

    assert patched == expected
    assert installed.read_bytes() == source
    assert guard._REPORT_SOURCE_SENTINEL not in patched
    assert patched.count(guard._REPORT_PATCHED_SENTINEL) == 1


@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda payload: payload + b"# drift\n", "G004"),
        (
            lambda payload: payload.replace(guard._REPORT_SOURCE_SENTINEL, b"# missing"),
            "G004",
        ),
        (
            lambda payload: payload.replace(
                guard._REPORT_SOURCE_SENTINEL,
                guard._REPORT_SOURCE_SENTINEL + b"\n" + guard._REPORT_SOURCE_SENTINEL,
            ),
            "G004",
        ),
    ],
)
def test_verified_report_patch_rejects_source_drift(monkeypatch, mutator, code):
    source = _synthetic_report_source()
    _configure_synthetic_report_hashes(monkeypatch, source)
    with pytest.raises(guard.GuardFailure, match=code):
        guard._verified_report_patch(mutator(source))


def test_verified_report_patch_rejects_an_unreviewed_result(monkeypatch):
    source = _synthetic_report_source()
    _configure_synthetic_report_hashes(monkeypatch, source)
    monkeypatch.setattr(guard, "EXPECTED_REPORT_PATCHED_SHA256", "0" * 64)
    with pytest.raises(guard.GuardFailure, match="G005"):
        guard._verified_report_patch(source)


def test_verified_rebuild_patch_is_exact(monkeypatch):
    source = _synthetic_watch_source()
    expected = _configure_synthetic_watch_hashes(monkeypatch, source)

    patched = guard._verified_rebuild_patch(source)

    assert patched == expected
    for source_sentinel, patched_sentinel in (
        (guard._REBUILD_COMMIT_SOURCE_SENTINEL, guard._REBUILD_COMMIT_PATCHED_SENTINEL),
        (guard._REBUILD_TOPOLOGY_SOURCE_SENTINEL, guard._REBUILD_TOPOLOGY_PATCHED_SENTINEL),
        (guard._REBUILD_FAST_SOURCE_SENTINEL, guard._REBUILD_FAST_PATCHED_SENTINEL),
        (guard._REBUILD_FINAL_SOURCE_SENTINEL, guard._REBUILD_FINAL_PATCHED_SENTINEL),
    ):
        assert source_sentinel not in patched
        assert patched.count(patched_sentinel) == 1


@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize(
    "source_sentinel",
    [
        guard._REBUILD_COMMIT_SOURCE_SENTINEL,
        guard._REBUILD_TOPOLOGY_SOURCE_SENTINEL,
        guard._REBUILD_FAST_SOURCE_SENTINEL,
        guard._REBUILD_FINAL_SOURCE_SENTINEL,
    ],
)
def test_verified_rebuild_patch_rejects_source_drift(
    monkeypatch, source_sentinel, duplicate
):
    source = _synthetic_watch_source()
    _configure_synthetic_watch_hashes(monkeypatch, source)
    replacement = source_sentinel + source_sentinel if duplicate else b"# missing"
    with pytest.raises(guard.GuardFailure, match="G004"):
        guard._verified_rebuild_patch(source.replace(source_sentinel, replacement, 1))


def test_verified_rebuild_patch_rejects_other_source_drift(monkeypatch):
    source = _synthetic_watch_source()
    _configure_synthetic_watch_hashes(monkeypatch, source)
    with pytest.raises(guard.GuardFailure, match="G004"):
        guard._verified_rebuild_patch(source + b"# drift\n")


def test_verified_rebuild_patch_rejects_an_unreviewed_result(monkeypatch):
    source = _synthetic_watch_source()
    _configure_synthetic_watch_hashes(monkeypatch, source)
    monkeypatch.setattr(guard, "EXPECTED_REBUILD_PATCHED_SHA256", "0" * 64)
    with pytest.raises(guard.GuardFailure, match="G005"):
        guard._verified_rebuild_patch(source)


@pytest.mark.skipif(
    not _reviewed_install_available(),
    reason="the exact official Graphifyy 0.9.51 extractor, reporter, and rebuild are not installed",
)
def test_real_report_overlay_changes_only_the_mixed_partition_summary():
    import networkx as nx

    distribution = metadata.distribution(guard.DIST_NAME)
    report_path = guard._locate_report(distribution)
    source = report_path.read_bytes()
    patched = guard._verified_report_patch(source)

    def compile_generate(payload):
        module = types.ModuleType(guard.REPORT_MODULE)
        module.__file__ = str(report_path)
        module.__package__ = "graphify"
        exec(compile(payload.decode("utf-8"), str(report_path), "exec"), module.__dict__)
        return module.generate

    original_generate = compile_generate(source)
    corrected_generate = compile_generate(patched)

    mixed = nx.Graph()
    for node in ("shown_a", "shown_b", "shown_c", "thin"):
        mixed.add_node(node, label=node, source_file=f"{node}.py")
    mixed.add_node("structural", label="structural.py", source_file="structural.py")
    communities = {
        1: ["shown_a", "shown_b", "shown_c"],
        2: ["thin"],
        3: ["structural"],
    }
    arguments = (
        mixed,
        communities,
        {},
        {},
        [],
        [],
        {"warning": "fixture"},
        {},
        ".",
    )
    original = original_generate(*arguments)
    corrected = corrected_generate(*arguments)

    assert "3 communities (2 shown, 1 thin omitted)" in original
    assert "3 communities (1 shown, 1 thin omitted)" in corrected
    assert original.replace("(2 shown, 1 thin omitted)", "(1 shown, 1 thin omitted)") == corrected
    assert corrected.count("### Community ") == 1

    all_structural = nx.Graph()
    all_structural.add_node("only", label="only.py", source_file="only.py")
    all_structural_arguments = (
        all_structural,
        {1: ["only"]},
        {},
        {},
        [],
        [],
        {"warning": "fixture"},
        {},
        ".",
    )
    assert original_generate(*all_structural_arguments) == corrected_generate(
        *all_structural_arguments
    )


@pytest.mark.skipif(
    not _reviewed_install_available(),
    reason="the exact official Graphifyy 0.9.51 extractor, reporter, and rebuild are not installed",
)
def test_real_rebuild_patch_changes_only_the_reviewed_commit_policy_regions():
    import graphify.watch as watch

    source = inspect.getsource(watch._rebuild_code).encode("utf-8")
    patched = guard._verified_rebuild_patch(source)

    pairs = (
        (guard._REBUILD_COMMIT_SOURCE_SENTINEL, guard._REBUILD_COMMIT_PATCHED_SENTINEL),
        (guard._REBUILD_TOPOLOGY_SOURCE_SENTINEL, guard._REBUILD_TOPOLOGY_PATCHED_SENTINEL),
        (guard._REBUILD_FAST_SOURCE_SENTINEL, guard._REBUILD_FAST_PATCHED_SENTINEL),
        (guard._REBUILD_FINAL_SOURCE_SENTINEL, guard._REBUILD_FINAL_PATCHED_SENTINEL),
    )
    expected = source
    for source_sentinel, patched_sentinel in pairs:
        expected = expected.replace(source_sentinel, patched_sentinel, 1)
    assert patched == expected
    assert len(patched) - len(source) == sum(
        len(patched_sentinel) - len(source_sentinel)
        for source_sentinel, patched_sentinel in pairs
    )


def test_distribution_path_and_version_are_fail_closed(tmp_path):
    wrong_version = _Distribution(tmp_path, version="0.9.48")
    with pytest.raises(guard.GuardFailure, match="G002"):
        guard._locate_extractor(wrong_version)

    ambiguous = _Distribution(tmp_path)
    ambiguous.files.append(PurePosixPath(guard.EXTRACTOR_RELATIVE_PATH))
    with pytest.raises(guard.GuardFailure, match="G003"):
        guard._locate_extractor(ambiguous)

    ambiguous_report = _Distribution(tmp_path)
    ambiguous_report.files.append(PurePosixPath(guard.REPORT_RELATIVE_PATH))
    with pytest.raises(guard.GuardFailure, match="G003"):
        guard._locate_report(ambiguous_report)

    ambiguous_watch = _Distribution(tmp_path)
    ambiguous_watch.files.append(PurePosixPath(guard.WATCH_RELATIVE_PATH))
    with pytest.raises(guard.GuardFailure, match="G003"):
        guard._locate_watch(ambiguous_watch)


def test_overlay_rebinds_every_live_0951_alias_and_changes_only_extends_arrays(
    tmp_path, monkeypatch
):
    (
        source_path,
        source,
        report_source_path,
        report_source,
        extractors,
        facade,
        graphify_package,
        report,
        get_distribution,
        import_module,
    ) = _overlay_harness(tmp_path, monkeypatch)

    receipt = guard._prepare_overlay(
        distribution_getter=get_distribution,
        module_importer=import_module,
    )

    overlay = sys.modules[guard.EXTRACTOR_MODULE]
    watch = import_module(guard.WATCH_MODULE)
    corrected = overlay.extract_json
    assert extractors.json_config is overlay
    assert extractors.extract_json is corrected
    assert extractors.LANGUAGE_EXTRACTORS["json"] is corrected
    assert facade.extract_json is corrected
    assert facade._DISPATCH[".json"] is corrected
    assert guard._JSON_SUFFIX_VARIANTS.issubset(facade._JS_CACHE_BYPASS_SUFFIXES)
    assert receipt["aliases"] == 5
    assert receipt["ast_cache"] == "bypass-json-casefold"
    assert receipt["contract"] == guard.GUARD_CONTRACT
    assert receipt["report"] == guard.REPORT_RELATIVE_PATH
    assert receipt["report_aliases"] == 1
    assert receipt["report_source_sha256"] == guard.EXPECTED_REPORT_SOURCE_SHA256
    assert receipt["report_patched_sha256"] == guard.EXPECTED_REPORT_PATCHED_SHA256
    assert receipt["watch"] == guard.WATCH_RELATIVE_PATH
    assert receipt["watch_aliases"] == 1
    assert receipt["watch_source_sha256"] == guard.EXPECTED_WATCH_SOURCE_SHA256
    assert receipt["rebuild_source_sha256"] == guard.EXPECTED_REBUILD_SOURCE_SHA256
    assert receipt["rebuild_patched_sha256"] == guard.EXPECTED_REBUILD_PATCHED_SHA256
    assert receipt["rebuild_commit_policy"] == (
        "rewrite_only_when_head_differs_and_non_provenance_graph_report_match"
    )
    assert source_path.read_bytes() == source
    assert report_source_path.read_bytes() == report_source
    assert get_distribution(guard.DIST_NAME).locate_file(
        PurePosixPath(guard.WATCH_RELATIVE_PATH)
    ).read_bytes() == _synthetic_watch_source()
    assert graphify_package.report is report

    value = types.SimpleNamespace(type="array")
    assert corrected(value, "extends") == "array"
    assert corrected(value, "required") == "other"
    assert report.generate({1: [], 2: [], 3: []}, {1: [], 2: []}, 1) == 1
    assert report.generate({1: []}, {}, 0) == 0
    watch._head = "a" * 40
    assert watch._rebuild_code({"built_at_commit": watch._head}) == "fast-noop"
    watch._head = "b" * 40
    assert watch._rebuild_code({"built_at_commit": "a" * 40}) == "rebuilt"
    watch._unlink_calls.clear()
    assert watch._rebuild_code(
        {"built_at_commit": "a" * 40}, same_graph=False
    ) is False
    assert watch._unlink_calls == [{"missing_ok": True}]
    watch._extract_calls.clear()
    watch._head = None
    assert watch._rebuild_code({"built_at_commit": "a" * 40}) is False
    assert not watch._extract_calls


@pytest.mark.parametrize(
    "invalid_head",
    [None, True, "A" * 40, "a" * 39, "g" * 40],
)
def test_rebuild_overlay_rejects_invalid_git_head_before_extraction(
    tmp_path, monkeypatch, invalid_head
):
    harness = _overlay_harness(tmp_path, monkeypatch)
    *_, get_distribution, import_module = harness
    guard._prepare_overlay(
        distribution_getter=get_distribution,
        module_importer=import_module,
    )
    watch = import_module(guard.WATCH_MODULE)
    watch._head = invalid_head
    watch._extract_calls.clear()

    assert watch._rebuild_code({"built_at_commit": "a" * 40}) is False
    assert not watch._extract_calls


@pytest.mark.parametrize("broken_alias", [
    "package_module", "package_function", "registry", "facade", "dispatch", "cache",
    "cache_identity", "report_package", "report_generate", "watch_rebuild",
])
def test_overlay_rejects_unexpected_alias_topology(tmp_path, monkeypatch, broken_alias):
    harness = _overlay_harness(tmp_path, monkeypatch)
    _, _, _, _, extractors, facade, graphify_package, report, get_distribution, import_module = harness
    if broken_alias == "package_module":
        extractors.json_config = types.ModuleType("wrong")
    elif broken_alias == "package_function":
        extractors.extract_json = lambda _path: None
    elif broken_alias == "registry":
        extractors.LANGUAGE_EXTRACTORS["json"] = lambda _path: None
    elif broken_alias == "facade":
        facade.extract_json = lambda _path: None
    elif broken_alias == "dispatch":
        facade._DISPATCH[".json"] = lambda _path: None
    elif broken_alias == "cache":
        facade._JS_CACHE_BYPASS_SUFFIXES = frozenset({".js"})
    elif broken_alias == "cache_identity":
        facade._JS_CACHE_BYPASS_SUFFIXES = set(facade._JS_CACHE_BYPASS_SUFFIXES)
    elif broken_alias == "report_package":
        graphify_package.report = types.ModuleType("wrong")
    elif broken_alias == "report_generate":
        report.generate = None
    else:
        import_module(guard.WATCH_MODULE)._rebuild_code = None

    with pytest.raises(guard.GuardFailure, match="G006"):
        guard._prepare_overlay(
            distribution_getter=get_distribution,
            module_importer=import_module,
        )


@pytest.mark.parametrize(
    "module_name",
    [guard.EXTRACTOR_MODULE, guard.REPORT_MODULE, guard.WATCH_MODULE],
)
def test_overlay_rejects_an_import_from_a_different_path(
    tmp_path, monkeypatch, module_name
):
    harness = _overlay_harness(tmp_path, monkeypatch)
    *_, get_distribution, import_module = harness
    import_module(module_name).__file__ = str(tmp_path / "elsewhere.py")
    with pytest.raises(guard.GuardFailure, match="G006"):
        guard._prepare_overlay(
            distribution_getter=get_distribution,
            module_importer=import_module,
        )


def test_probe_output_is_fixed_machine_readable_receipt(monkeypatch, capsys):
    receipt = {
        "aliases": 5,
        "ast_cache": "bypass-json-casefold",
        "contract": guard.GUARD_CONTRACT,
        "extractor": guard.EXTRACTOR_RELATIVE_PATH,
        "max_workers": 1,
        "patched_sha256": guard.EXPECTED_PATCHED_SHA256,
        "report": guard.REPORT_RELATIVE_PATH,
        "report_aliases": 1,
        "report_patched_sha256": guard.EXPECTED_REPORT_PATCHED_SHA256,
        "report_source_sha256": guard.EXPECTED_REPORT_SOURCE_SHA256,
        "source_sha256": guard.EXPECTED_SOURCE_SHA256,
        "status": "pass",
        "version": guard.EXPECTED_VERSION,
    }
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: receipt)

    assert guard.main(["--probe"]) == 0
    captured = capsys.readouterr()
    expected = {
        **receipt,
        "bytecode_writes": "disabled",
        "environment": "graphify-git-path-sanitized",
        "isolated": True,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
    }
    assert json.loads(captured.out) == expected
    assert captured.out == json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
    assert not captured.err


def test_nonisolated_invocation_is_rejected_before_import(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(guard, "_invocation_isolated", lambda: False)
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: called.append(True))

    assert guard.main(["--probe"]) == 2
    captured = capsys.readouterr()
    assert not called
    assert not captured.out
    assert "G014" in captured.err
    assert "-I -B" in captured.err


def test_refresh_receipt_is_atomic_phase_and_guard_bound(tmp_path, monkeypatch, capsys):
    root = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    tracked = root / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline"],
        cwd=root,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = root / "graphify-out"
    output.mkdir()
    graph_path = output / "graph.json"
    graph_bytes = json.dumps(
        {"built_at_commit": head, "nodes": [], "links": []},
        separators=(",", ":"),
    ) + "\n"
    graph_path.write_text(graph_bytes, encoding="utf-8")
    receipt_path = output / ".guarded_refresh.json"
    guard_receipt = {
        "contract": guard.GUARD_CONTRACT,
        "max_workers": 1,
        "source_sha256": guard.EXPECTED_SOURCE_SHA256,
        "status": "pass",
    }
    monkeypatch.chdir(root)
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: dict(guard_receipt))
    args = [str(receipt_path), head, "clean"]

    fake_head_args = [str(receipt_path), "f" * 40, "clean"]
    assert guard.main(["--receipt-pending", *fake_head_args]) == 2
    assert not receipt_path.exists()
    assert guard.main(["--receipt-status", *args]) == 1
    assert guard.main(["--receipt-pending", *args]) == 0
    pending = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert pending["contract"] == guard.REFRESH_RECEIPT_CONTRACT
    assert pending["phase"] == "pending"
    assert pending["head"] == head and pending["state"] == "clean"
    assert guard.main(["--receipt-status", *args]) == 1

    assert guard.main(["--receipt-complete", *args]) == 0
    assert guard.main(["--receipt-status", *args]) == 0
    graph_path.write_text('{"corrupted":true}\n', encoding="utf-8")
    assert guard.main(["--receipt-status", *args]) == 2
    graph_path.write_text(graph_bytes, encoding="utf-8")
    graph_path.write_text(
        json.dumps({"built_at_commit": "f" * 40, "nodes": [], "links": []}) + "\n",
        encoding="utf-8",
    )
    assert guard.main(["--receipt-status", *args]) == 2
    graph_path.write_text(graph_bytes, encoding="utf-8")
    assert guard.main(["--receipt-complete", *args]) == 2
    assert guard.main(["--receipt-pending", *args]) == 0
    assert guard.main(["--receipt-complete", *args]) == 0
    dirty_args = [str(receipt_path), head, "dirty"]
    assert guard.main(["--receipt-complete", *dirty_args]) == 2
    assert guard.main(["--receipt-pending", *dirty_args]) == 2
    tracked.write_text("dirty\n", encoding="utf-8")
    assert guard.main(["--receipt-pending", *dirty_args]) == 0
    assert guard.main(["--receipt-complete", *dirty_args]) == 0
    assert guard.main(["--receipt-status", *dirty_args]) == 1
    tracked.write_text("tracked\n", encoding="utf-8")
    assert guard.main(["--receipt-pending", *args]) == 0
    assert guard.main(["--receipt-complete", *args]) == 0

    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered.pop("updated_at")
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert guard.main(["--receipt-status", *args]) == 1
    assert guard.main(["--receipt-complete", *args]) == 2
    assert guard.main(["--receipt-pending", *args]) == 0
    assert guard.main(["--receipt-complete", *args]) == 0

    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["guard"]["max_workers"] = True
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert guard.main(["--receipt-status", *args]) == 1
    assert guard.main(["--receipt-pending", *args]) == 0
    assert guard.main(["--receipt-complete", *args]) == 0
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["graph"]["size"] = float(tampered["graph"]["size"])
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert guard.main(["--receipt-status", *args]) == 1

    monkeypatch.setattr(
        guard,
        "_prepare_overlay",
        lambda: {**guard_receipt, "source_sha256": "0" * 64},
    )
    assert guard.main(["--receipt-status", *args]) == 1
    assert "G017" in capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [
        '{"nodes":[],"links":[]}\n',
        '{"built_at_commit":null,"nodes":[],"links":[]}\n',
        '{"built_at_commit":true,"nodes":[],"links":[]}\n',
        '{"built_at_commit":"ABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD","nodes":[],"links":[]}\n',
        '{"built_at_commit":"abc","nodes":[],"links":[]}\n',
        '{"built_at_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","built_at_commit":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","nodes":[],"links":[]}\n',
    ],
)
def test_graph_snapshot_rejects_missing_malformed_or_duplicate_commit(tmp_path, payload):
    graph = tmp_path / "graph.json"
    graph.write_text(payload, encoding="utf-8")
    with pytest.raises(guard.GuardFailure, match="G017"):
        guard._graph_snapshot(graph)


def test_graph_snapshot_rejects_named_path_replacement(tmp_path, monkeypatch):
    graph = tmp_path / "graph.json"
    replacement = tmp_path / "replacement.json"
    first = json.dumps(
        {"built_at_commit": "a" * 40, "nodes": [], "links": []}
    ) + "\n"
    second = json.dumps(
        {"built_at_commit": "a" * 40, "nodes": [{"id": "changed"}], "links": []}
    ) + "\n"
    graph.write_text(first, encoding="utf-8")
    replacement.write_text(second, encoding="utf-8")
    real_stat = guard.os.stat
    real_fstat = guard.os.fstat
    replaced = False
    fstat_calls = 0

    def track_handle_stats(descriptor):
        nonlocal fstat_calls
        fstat_calls += 1
        return real_fstat(descriptor)

    def replace_before_named_stat(path, *args, **kwargs):
        nonlocal replaced
        if (
            not replaced
            and fstat_calls >= 2
            and Path(path) == graph
            and kwargs.get("follow_symlinks") is False
        ):
            replacement.replace(graph)
            replaced = True
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(guard.os, "fstat", track_handle_stats)
    monkeypatch.setattr(guard.os, "stat", replace_before_named_stat)
    with pytest.raises(guard.GuardFailure, match="G017"):
        guard._graph_snapshot(graph)
    assert replaced


def test_graph_snapshot_rejects_hardlinked_graph(tmp_path):
    graph = tmp_path / "graph.json"
    alias = tmp_path / "graph-alias.json"
    graph.write_text(
        json.dumps({"built_at_commit": "a" * 40, "nodes": [], "links": []}) + "\n",
        encoding="utf-8",
    )
    try:
        os.link(graph, alias)
    except OSError as exc:
        pytest.skip(f"same-volume hardlinks are unavailable: {exc}")
    with pytest.raises(guard.GuardFailure, match="G017"):
        guard._graph_snapshot(graph)


def test_refresh_receipt_refuses_an_already_held_producer_lock(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline"],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "graphify-out"
    output.mkdir()
    (output / "graph.json").write_text(
        json.dumps({"built_at_commit": head, "nodes": [], "links": []}) + "\n",
        encoding="utf-8",
    )
    receipt = output / ".guarded_refresh.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(guard, "_producer_root", _REAL_PRODUCER_ROOT)
    monkeypatch.setattr(guard, "_producer_lock", _REAL_PRODUCER_LOCK)
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: {"status": "pass"})

    with _REAL_PRODUCER_LOCK(tmp_path.resolve()):
        assert guard.main([
            "--receipt-pending", str(receipt), head, "clean"
        ]) == 2
    assert not receipt.exists()


def test_refresh_receipt_rejects_wrong_path_or_head_before_write(tmp_path, monkeypatch, capsys):
    (tmp_path / "graphify-out").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: {"status": "pass"})

    assert guard.main([
        "--receipt-pending", str(tmp_path / "elsewhere.json"), "a" * 40, "clean"
    ]) == 2
    assert guard.main([
        "--receipt-pending",
        str(tmp_path / guard.REFRESH_RECEIPT_PATH),
        "not-a-head",
        "clean",
    ]) == 2
    assert "G017" in capsys.readouterr().err


def test_probe_with_extra_arguments_is_rejected_before_import(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: called.append(True))
    assert guard.main(["--probe", "update"]) == 2
    captured = capsys.readouterr()
    assert not called
    assert not captured.out
    assert "G009" in captured.err
    assert len(captured.err) < 200


@pytest.mark.parametrize("arguments", [["extract", ".", "--max-workers", "2"], [
    "extract", ".", "--max-workers=2"
]])
def test_worker_override_is_rejected_before_import(monkeypatch, capsys, arguments):
    called = []
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: called.append(True))
    assert guard.main(arguments) == 2
    captured = capsys.readouterr()
    assert not called
    assert not captured.out
    assert "G010" in captured.err
    assert "single-process AST extraction" in captured.err


@pytest.mark.parametrize("arguments,code", [
    ([], "G011"),
    (["query", "anything"], "G011"),
    (["add", "https://example.invalid"], "G011"),
    (["update"], "G013"),
    (["update", "--force"], "G013"),
    (["update", ".", "--no-cluster"], "G013"),
    (["watch"], "G013"),
    (["extract", "."], "G012"),
    (["extract", ".", "--code-only", "--backend", "openai"], "G013"),
    (["extract", ".", "--code-only", "--allow-partial"], "G013"),
    (["extract", ".", "--code-only", "--no-gitignore"], "G013"),
    (["extract", ".", "--code-only", "--force"], "G013"),
    (["extract", ".", "--code-only", "--out", "elsewhere"], "G013"),
    (["extract", "https://example.invalid/source", "--code-only"], "G012"),
    (["update", "https://example.invalid/source"], "G013"),
    (["watch", "//server/share"], "G013"),
    (["watch", ".", "extra"], "G013"),
    (["update", ".", "extra"], "G013"),
])
def test_guarded_command_surface_is_closed_before_import(monkeypatch, capsys, arguments, code):
    called = []
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: called.append(True))
    assert guard.main(arguments) == 2
    captured = capsys.readouterr()
    assert not called
    assert not captured.out
    assert code in captured.err


def test_pathless_update_cannot_reuse_a_saved_unc_root(tmp_path, monkeypatch, capsys):
    saved = tmp_path / "graphify-out" / ".graphify_root"
    saved.parent.mkdir()
    saved.write_text("//server/out-of-scope\n", encoding="utf-8")
    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: called.append(True))

    assert guard.main(["update"]) == 2
    captured = capsys.readouterr()
    assert not called
    assert not captured.out
    assert "G013" in captured.err


def test_producer_root_rejects_subdirectories_and_linked_worktrees(tmp_path):
    repo = tmp_path / "main"
    linked = tmp_path / "linked"
    repo.mkdir()

    def git(*arguments):
        subprocess.run(
            ["git", *arguments], cwd=repo, check=True, capture_output=True, text=True
        )

    git("init", "-q")
    (repo / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", "tracked.py")
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline")
    with pytest.raises(guard.GuardFailure, match="G016"):
        _REAL_PRODUCER_ROOT(["update", str(repo)])
    (repo / "graphify-out").mkdir()
    (repo / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")
    assert _REAL_PRODUCER_ROOT(["update", str(repo)]) == repo.resolve()

    subdir = repo / "subdir"
    subdir.mkdir()
    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["extract", str(subdir), "--code-only"])

    git("worktree", "add", "-q", "-b", "linked-review", str(linked))
    (linked / "graphify-out").mkdir()
    (linked / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["update", str(linked)])


def test_producer_root_rejects_output_indirection_when_supported(tmp_path):
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "graphify-out").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["extract", str(root), "--code-only"])


def test_producer_root_rejects_graph_file_indirection_when_supported(tmp_path):
    root = tmp_path / "source"
    output = root / "graphify-out"
    outside = tmp_path / "outside-graph.json"
    output.mkdir(parents=True)
    outside.write_text("{}\n", encoding="utf-8")
    try:
        (output / "graph.json").symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["update", str(root)])


def test_producer_root_rejects_nested_cache_indirection_when_supported(tmp_path):
    root = tmp_path / "source"
    cache = root / "graphify-out" / "cache"
    outside = tmp_path / "outside-cache"
    cache.mkdir(parents=True)
    outside.mkdir()
    (root / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")
    try:
        (cache / "ast").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["update", str(root)])


def test_producer_root_accepts_ordinary_output_files_but_rejects_hardlinks(tmp_path):
    root = tmp_path / "source"
    output = root / "graphify-out"
    output.mkdir(parents=True)
    (output / "graph.json").write_text("{}\n", encoding="utf-8")
    (output / "ordinary.json").write_text("{}\n", encoding="utf-8")
    assert _REAL_PRODUCER_ROOT(["update", str(root)]) == root.resolve()

    outside = tmp_path / "outside.txt"
    outside.write_text("preserve\n", encoding="utf-8")
    try:
        os.link(outside, output / ".graphify_root")
    except OSError:
        pytest.skip("same-volume hardlinks are unavailable")
    with pytest.raises(guard.GuardFailure, match="G015"):
        _REAL_PRODUCER_ROOT(["update", str(root)])
    assert outside.read_text(encoding="utf-8") == "preserve\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path contract")
def test_producer_root_accepts_legitimate_long_generated_output(tmp_path):
    root = tmp_path / "source"
    output = root / "graphify-out"
    output.mkdir(parents=True)
    (output / "graph.json").write_text("{}\n", encoding="utf-8")
    deep = output / ("a" * 120) / ("b" * 120)
    try:
        os.makedirs(guard._native_long_path(deep))
        long_file = deep / ("c" * 80 + ".md")
        with open(guard._native_long_path(long_file), "w", encoding="utf-8") as handle:
            handle.write("generated note\n")
    except OSError as exc:
        pytest.skip(f"host has no long-path support: {exc}")

    assert _REAL_PRODUCER_ROOT(["update", str(root)]) == root.resolve()


def test_real_producer_lock_is_nonblocking_and_reusable(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    with _REAL_PRODUCER_LOCK(root):
        with pytest.raises(guard.GuardFailure, match="G018"):
            with _REAL_PRODUCER_LOCK(root):
                pass
    with _REAL_PRODUCER_LOCK(root):
        pass


def test_producer_root_matches_graphifys_literal_tilde_semantics(tmp_path, monkeypatch):
    literal = tmp_path / "~"
    home = tmp_path / "home"
    literal.mkdir()
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))

    root = _REAL_PRODUCER_ROOT(["extract", "~", "--code-only"])
    arguments = guard._canonical_arguments(["extract", "~", "--code-only"], root)

    assert root == literal.resolve()
    assert arguments[1] == str(literal.resolve())


def test_guard_failure_is_bounded_and_never_enters_graphify(monkeypatch, capsys):
    invoked = []

    def fail():
        raise guard.GuardFailure("G004")

    monkeypatch.setattr(guard, "_prepare_overlay", fail)
    monkeypatch.setattr(guard, "_run_graphify", lambda _args: invoked.append(True))
    assert guard.main(["update", "."]) == 2
    captured = capsys.readouterr()
    assert not invoked
    assert not captured.out
    assert captured.err == (
        "graphify-guard: G004: the Graphify bytes do not match the reviewed 0.9.51 sources; "
        "no Graphify command was run.\n"
    )


def test_cli_passthrough_happens_after_overlay_and_restores_argv(monkeypatch):
    events = []
    original_argv = sys.argv

    def prepare():
        events.append("overlay")
        return {}

    cli = types.SimpleNamespace(main=lambda: events.append(
        ("cli", tuple(sys.argv), os.environ.get(guard.WORKER_ENV))))
    real_import_module = guard.importlib.import_module

    def import_module(name):
        if name == "graphify.__main__":
            return cli
        return real_import_module(name)

    monkeypatch.setattr(guard, "_prepare_overlay", prepare)
    monkeypatch.setattr(guard.importlib, "import_module", import_module)
    monkeypatch.setenv(guard.WORKER_ENV, "8")
    assert guard.main(["update", "."]) == 0
    assert events == [
        "overlay",
        ("cli", ("graphify", "update", str(Path.cwd().resolve())), "1"),
    ]
    assert sys.argv is original_argv
    assert os.environ[guard.WORKER_ENV] == "8"


def test_ambient_graphify_and_git_controls_are_sanitized_and_restored(monkeypatch):
    seen = []
    prefixes = ("GRAPHIFY_", "GIT_")

    def prepare():
        seen.append({key: value for key, value in os.environ.items() if key.startswith(prefixes)})
        return {}

    monkeypatch.setattr(guard, "_prepare_overlay", prepare)
    monkeypatch.setattr(
        guard,
        "_run_graphify",
        lambda _args: seen.append({
            key: value for key, value in os.environ.items() if key.startswith(prefixes)
        }) or 0,
    )
    monkeypatch.setenv("GRAPHIFY_FORCE", "1")
    monkeypatch.setenv("GRAPHIFY_OUT", "redirected")
    monkeypatch.setenv("GRAPHIFY_NO_BACKUP", "1")
    monkeypatch.setenv("GRAPHIFY_FUTURE_PRODUCER_OVERRIDE", "surprise")
    monkeypatch.setenv("GIT_DIR", "elsewhere/.git")
    monkeypatch.setenv("GIT_FUTURE_PRODUCER_OVERRIDE", "surprise")
    monkeypatch.setenv(guard.WORKER_ENV, "8")

    assert guard.main(["update", "."]) == 0
    assert seen == [
        {guard.WORKER_ENV: guard.GUARDED_MAX_WORKERS},
        {guard.WORKER_ENV: guard.GUARDED_MAX_WORKERS},
    ]
    assert os.environ["GRAPHIFY_FORCE"] == "1"
    assert os.environ["GRAPHIFY_OUT"] == "redirected"
    assert os.environ["GRAPHIFY_NO_BACKUP"] == "1"
    assert os.environ["GRAPHIFY_FUTURE_PRODUCER_OVERRIDE"] == "surprise"
    assert os.environ["GIT_DIR"] == "elsewhere/.git"
    assert os.environ["GIT_FUTURE_PRODUCER_OVERRIDE"] == "surprise"
    assert os.environ[guard.WORKER_ENV] == "8"


def test_relative_and_repo_local_executable_paths_are_excluded(monkeypatch, tmp_path):
    outside = tmp_path / "outside-bin"
    outside.mkdir()
    root = Path.cwd().resolve()
    original_path = os.environ.get("PATH")
    original_no_current = os.environ.get("NoDefaultCurrentDirectoryInExePath")
    observed = {}

    def prepare():
        observed["path"] = os.environ.get("PATH", "")
        observed["no_current"] = os.environ.get("NoDefaultCurrentDirectoryInExePath")
        return {}

    monkeypatch.setattr(guard, "_prepare_overlay", prepare)
    monkeypatch.setattr(guard, "_run_graphify", lambda _args: 0)
    monkeypatch.setenv("PATH", os.pathsep.join((".", str(root), str(outside))))

    assert guard.main(["update", "."]) == 0
    assert observed["path"].split(os.pathsep) == [str(outside.resolve())]
    if os.name == "nt":
        assert observed["no_current"] == "1"
    assert os.environ.get("PATH") == os.pathsep.join((".", str(root), str(outside)))
    assert os.environ.get("NoDefaultCurrentDirectoryInExePath") == original_no_current
    assert original_path is not None  # prove the test did not inherit an unusable environment


def test_probe_mode_cannot_resolve_an_executable_from_its_cwd(monkeypatch, tmp_path):
    name = "guardpathprobe.exe" if os.name == "nt" else "guardpathprobe"
    candidate = tmp_path / name
    candidate.write_bytes(b"not executable code\n")
    candidate.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))

    with guard._controlled_environment(None):
        assert shutil.which("guardpathprobe") is None


def test_graphify_runtime_failure_is_not_misreported_as_a_preflight_failure(monkeypatch, capsys):
    monkeypatch.setattr(guard, "_prepare_overlay", lambda: {})
    monkeypatch.setenv(guard.WORKER_ENV, "8")
    cli = types.SimpleNamespace(main=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        guard.importlib,
        "import_module",
        lambda name: cli if name == "graphify.__main__" else None,
    )

    with pytest.raises(RuntimeError, match="boom"):
        guard.main(["update", "."])
    assert os.environ[guard.WORKER_ENV] == "8"
    assert not capsys.readouterr().err


@pytest.mark.skipif(
    not _reviewed_install_available(),
    reason="the exact official Graphifyy 0.9.51 extractor, reporter, and rebuild are not installed",
)
def test_real_guarded_update_rebinds_only_tree_identical_commit_provenance(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    guard_path = Path(guard.__file__).resolve()

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def guarded(*arguments, expected=0):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(guard_path), *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == expected, (completed.stdout + completed.stderr)[-4_000:]
        return completed

    git("init", "-q")
    (repo / ".gitignore").write_text("graphify-out/\n", encoding="utf-8")
    (repo / "source.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    git("add", ".gitignore", "source.py")
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "initial")
    guarded("extract", str(repo), "--code-only")

    (repo / "extra.py").write_text("def second():\n    return 2\n", encoding="utf-8")
    git("add", "extra.py")
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "baseline")
    baseline_head = git("rev-parse", "HEAD")
    guarded("update", str(repo))

    graph_path = repo / "graphify-out" / "graph.json"
    report_path = repo / "graphify-out" / "GRAPH_REPORT.md"
    graph_baseline = graph_path.read_bytes()
    report_baseline = report_path.read_bytes()
    graph_mtime = graph_path.stat().st_mtime_ns
    assert json.loads(graph_baseline)["built_at_commit"] == baseline_head

    guarded("update", str(repo))
    assert graph_path.read_bytes() == graph_baseline
    assert report_path.read_bytes() == report_baseline
    assert graph_path.stat().st_mtime_ns == graph_mtime

    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "merge-like")
    merge_like_head = git("rev-parse", "HEAD")
    assert git("rev-parse", "HEAD^{tree}") == git("rev-parse", f"{baseline_head}^{{tree}}")
    guarded("update", str(repo))
    graph_rebound = graph_path.read_bytes()
    report_rebound = report_path.read_bytes()
    rebound_object = json.loads(graph_rebound)
    baseline_object = json.loads(graph_baseline)
    assert rebound_object.pop("built_at_commit") == merge_like_head
    assert baseline_object.pop("built_at_commit") == baseline_head
    assert rebound_object == baseline_object
    assert report_rebound.replace(merge_like_head[:8].encode(), baseline_head[:8].encode(), 1) == report_baseline

    rebound_mtime = graph_path.stat().st_mtime_ns
    guarded("update", str(repo))
    assert graph_path.read_bytes() == graph_rebound
    assert report_path.read_bytes() == report_rebound
    assert graph_path.stat().st_mtime_ns == rebound_mtime

    invalid_head_code = f'''\
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("guard_runtime", {str(guard_path)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._prepare_overlay()
import graphify.watch as watch
watch._git_head = lambda cwd=None: None
result = watch._rebuild_code(Path({str(repo)!r}), block_on_lock=True)
print(f"RESULT={{result!r}}")
'''
    invalid_head = subprocess.run(
        [sys.executable, "-I", "-B", "-c", invalid_head_code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert invalid_head.returncode == 0, invalid_head.stderr
    assert "RESULT=False" in invalid_head.stdout
    assert graph_path.read_bytes() == graph_rebound
    assert report_path.read_bytes() == report_rebound

    report_path.write_bytes(report_rebound + b"non-provenance drift\n")
    drifted_report = report_path.read_bytes()
    git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "refuse-drift")
    guarded("update", str(repo), expected=1)
    assert graph_path.read_bytes() == graph_rebound
    assert report_path.read_bytes() == drifted_report
    assert not (repo / "graphify-out" / ".graph.tmp.json").exists()


@pytest.mark.skipif(
    not _reviewed_install_available(),
    reason="the exact official Graphifyy 0.9.51 extractor, reporter, and rebuild are not installed",
)
def test_real_guarded_cli_keeps_a_parallel_sized_json_batch_on_the_overlay(tmp_path):
    """Twenty files would spawn workers that reload the faulty disk module without the policy."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    for index in range(20):
        suffix = "JSON" if index == 0 else "json"
        (source_root / f"p{index:02d}.tsconfig.{suffix}").write_text(
            '{"compilerOptions":{},"required":["not-an-extends-ref"]}\n',
            encoding="utf-8",
        )

    # Seed the official v0.9.51-s2 AST cache with a false relation for the
    # identical bytes. The guard must preserve but never replay this entry.
    from graphify.cache import save_cached

    poisoned_path = source_root / "p00.tsconfig.JSON"
    save_cached(
        poisoned_path,
        {
            "nodes": [{
                "id": "poison_required",
                "label": "required",
                "source_file": str(poisoned_path),
                "source_location": "L1",
            }],
            "edges": [{
                "source": "poison_required",
                "target": "poison_ref",
                "relation": "extends",
                "source_file": str(poisoned_path),
                "source_location": "L1",
            }],
        },
        root=source_root,
        cache_root=source_root,
    )
    poisoned_cache = next(
        (source_root / "graphify-out" / "cache" / "ast" / "v0.9.51-s2").glob("*.json")
    )
    poisoned_bytes = poisoned_cache.read_bytes()

    distribution = metadata.distribution(guard.DIST_NAME)
    relative = next(
        item for item in distribution.files or ()
        if str(item).replace("\\", "/") == guard.EXTRACTOR_RELATIVE_PATH
    )
    installed_source = Path(distribution.locate_file(relative))
    before = hashlib.sha256(installed_source.read_bytes()).hexdigest()
    report_relative = next(
        item for item in distribution.files or ()
        if str(item).replace("\\", "/") == guard.REPORT_RELATIVE_PATH
    )
    installed_report_source = Path(distribution.locate_file(report_relative))
    report_before = hashlib.sha256(installed_report_source.read_bytes()).hexdigest()
    env = dict(os.environ)
    env[guard.WORKER_ENV] = "8"  # the wrapper must replace this attempted bypass
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(guard.__file__).resolve()),
            "extract",
            str(source_root),
            "--code-only",
            "--no-cluster",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-4_000:]

    graph = json.loads(
        (source_root / "graphify-out" / "graph.json").read_text(encoding="utf-8")
    )
    links = graph.get("links", graph.get("edges", []))
    assert not [edge for edge in links if edge.get("relation") == "extends"]
    assert poisoned_cache.read_bytes() == poisoned_bytes
    assert hashlib.sha256(installed_source.read_bytes()).hexdigest() == before
    assert hashlib.sha256(installed_report_source.read_bytes()).hexdigest() == report_before
