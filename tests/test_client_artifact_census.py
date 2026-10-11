"""W65: every write site is classified, and both privacy gates refuse every client class.

Before W65 the committed-tree gate (``.github/scripts/verify_repository_privacy.py``) and the
wheel/sdist audit (``cisco_toolkit/distribution_verify.py``) each kept a hand-written suffix list.
The engine meanwhile wrote ``.protocol-assurance.json``, ``.comparison.json``,
``.trend-comparisons.json`` and ``.phase_timings.json`` sidecars, all naming client devices, that
neither list classified. That is the "named subset instead of the structural class" defect, so the
fix is structural rather than four more list entries:

* ONE owner of client-artifact name classes, ``distribution_verify.CLIENT_ARTIFACT_NAME_CLASSES``,
  consumed by the archive audit and restated (pinned equal, data and behaviour) by the stdlib-only
  repository gate;
* a census (``tests/client_artifact_census.py``) of every write site in every tracked non-test
  Python file, found by AST, so a new write or a new caller of a path-parameter writer fails here
  until it is classified, and a row must name every class its sites resolve to;
* ties from producer-owned names (docmeta, ingest markers, gate state, recall, COMMANDS_*, REST
  collectors, browser downloads, ``Content-Disposition`` names, the PowerShell backup writer) and
  from the raw-capture owner of record to the registry, and from the registry to ``.gitignore``,
  the reviewed fixture manifest and the tracked tree.

Every check below is exercised with a negative control: a synthetic tree, path or literal the
check must reject.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

import client_artifact_census as census  # tests/ is on sys.path (root conftest.py)
from cisco_toolkit import distribution_verify as dv
from cisco_toolkit import docmeta, gate_state, recall
from cisco_toolkit import engine_log_path
from portable.release_contract import _forbidden_client_artifact as bundle_client_name

ROOT = Path(__file__).resolve().parents[1]
CLASSES = tuple((key, match, pattern) for key, match, pattern, _producer in dv.CLIENT_ARTIFACT_NAME_CLASSES)
# The four sidecars the W59 round-3 fixer found unclassified by both gates.
UNGUARDED_BEFORE_W65 = {
    "protocol-assurance-export": ".protocol-assurance.json",
    "comparison-receipt": ".comparison.json",
    "trend-comparisons": ".trend-comparisons.json",
    "phase-timings": ".phase_timings.json",
}


@functools.lru_cache(maxsize=1)
def _repository_gate():
    path = ROOT / ".github" / "scripts" / "verify_repository_privacy.py"
    spec = importlib.util.spec_from_file_location("_w65_repository_privacy", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=1)
def _raw_capture_owner():
    """``webapp/backend/redaction_verify.py :: is_uncoverable_capture``, the raw-capture owner."""
    path = ROOT / "webapp" / "backend" / "redaction_verify.py"
    spec = importlib.util.spec_from_file_location("_w65_redaction_verify", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.is_uncoverable_capture


def _probe(match: str, pattern: str) -> str:
    """A path a producer of this class could write, outside any reviewed fixture."""
    if match == "suffix":
        return f"customer-output/Acme{pattern}"
    if match == "leaf":
        return f"customer-output/{pattern}"
    if match == "leaf-prefix":
        return f"customer-output/{pattern}probe.html"
    if match == "contains":
        return f"customer-output/CORE-1{pattern}"
    if match == "capture":
        return f"customer-output/CORE-1/{pattern}probe.txt"
    raise AssertionError(f"unknown match kind {match!r}")


def _git() -> str:
    git = shutil.which("git")
    assert git is not None, "git is required to verify the ignore and tracked-tree contracts"
    return git


def _tracked() -> list[str]:
    listed = subprocess.run([_git(), "ls-files", "-z"], cwd=ROOT, check=True,
                            capture_output=True).stdout.decode("utf-8").split("\0")
    return [path for path in listed if path]


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- the write-site census


def test_every_write_site_is_classified():
    problems = census.census_problems(ROOT)
    assert problems == [], "\n".join(problems)


def test_every_output_name_suffix_literal_is_classified():
    problems = census.suffix_literal_problems(ROOT)
    assert problems == [], "\n".join(problems)


def test_the_census_scans_every_tracked_non_test_python_file():
    """Scope is derived, not listed: every tracked .py file except test code."""
    tracked = {path for path in _tracked() if path.endswith(".py")}
    scanned = set(census.scanned_files(ROOT))
    assert len(scanned) > 200
    assert scanned == {path for path in tracked if not census.is_test_path(path)}
    # The roots W65 began with are inside the derived scope, and so is everything else tracked.
    for root in ("COLLECT_PARSE_V3_23_0.py", "cisco_toolkit/", "webapp/backend/", "portable/",
                 "tools/", ".github/scripts/", "master-reference/", "research_lane/"):
        assert any(path == root or path.startswith(root) for path in scanned), root
    for path in ("tests/test_client_artifact_census.py", "tests/client_artifact_census.py",
                 "conftest.py", "webapp/tests/conftest.py", ".github/scripts/test_x.py"):
        assert census.is_test_path(path), path
    assert not census.is_test_path("cisco_toolkit/attestation.py")


def test_the_census_reaches_the_sidecars_both_gates_used_to_miss():
    sites = census.write_sites(ROOT)
    assert len(sites) >= 200 and sum(sites.values()) >= 400, "the census found too few write sites"
    rows = census.WRITE_SITE_CENSUS
    assert {"comparison-receipt", "trend-comparisons"} <= set(rows["COLLECT_PARSE_V3_23_0.py::main"][2])
    assert {"protocol-assurance-export", "phase-timings", "run-manifest", "incomplete-marker"} <= set(
        rows["COLLECT_PARSE_V3_23_0.py::_stage_finalize"][2])
    resolved = census.resolved_site_classes(ROOT)
    assert {"comparison-receipt", "trend-comparisons", "pre-change-certificate"} <= resolved[
        "COLLECT_PARSE_V3_23_0.py::main"]
    assert {"protocol-assurance-export", "phase-timings"} <= resolved[
        "COLLECT_PARSE_V3_23_0.py::_stage_finalize"]
    literals = {literal for _location, literal in census.suffix_literals(ROOT)}
    assert set(UNGUARDED_BEFORE_W65.values()) <= literals
    for key, suffix in UNGUARDED_BEFORE_W65.items():
        assert dv.client_artifact_class(f"out/Acme{suffix}") == key


def test_in_place_collection_rewrites_are_operator_path_rows_with_the_raw_capture_shapes():
    """P2: the two in-place rewriters publish the owner's open class, not just the seven prefixes."""
    rows = census.WRITE_SITE_CENSUS
    for key in ("cisco_toolkit/html.py::redact_collection_dir",
                "webapp/backend/ingest.py::_copy_back_scrubbed_collection"):
        _count, disposition, keys, why = rows[key]
        assert disposition == census.OPERATOR_PATH
        assert set(census._RAW_CAPTURE_SHAPES) <= set(keys)
        assert "is_uncoverable_capture" in why
    # The scrub skips structured .json, so it never publishes the collection sidecars.
    assert not set(census._COLLECTION_SIDECARS) & set(rows["cisco_toolkit/html.py::redact_collection_dir"][2])


def _engine_tree(tmp_path: Path, body: str) -> Path:
    _write(tmp_path, "COLLECT_PARSE_V3_23_0.py",
           "def write_json_file(path, data):\n"
           "    with open(path, 'w', encoding='utf-8') as handle:\n"
           "        handle.write(str(data))\n" + body)
    return tmp_path


_BASE_ROW = {"COLLECT_PARSE_V3_23_0.py::write_json_file": (1, census.DELEGATED, (), "generic writer")}


def test_a_new_caller_of_a_derived_writer_fails_the_census(tmp_path):
    root = _engine_tree(tmp_path, "\n\ndef emit(base):\n    write_json_file(base + '.new.json', {})\n")
    _counts, writers = census.scan(root)
    assert "COLLECT_PARSE_V3_23_0.py::write_json_file" in writers, "the path parameter was not derived"
    problems = census.census_problems(root, census=_BASE_ROW, registry_keys=["snapshot"])
    assert problems == ["unclassified write site: COLLECT_PARSE_V3_23_0.py::emit (1 write(s))"]
    literal_problems = census.suffix_literal_problems(root, non_client={})
    assert len(literal_problems) == 1 and "'.new.json'" in literal_problems[0]
    classified = {**_BASE_ROW, "COLLECT_PARSE_V3_23_0.py::emit": (1, census.CLIENT, ("snapshot",), "x")}
    assert census.census_problems(root, census=classified, registry_keys=["snapshot"]) == [
        "client write site resolves to unclassified name '0.new.json': COLLECT_PARSE_V3_23_0.py::emit"
    ]


def test_a_writer_that_only_forwards_its_path_is_derived_too(tmp_path):
    root = _engine_tree(
        tmp_path,
        "\n\ndef forward(target, payload):\n    write_json_file(target, payload)\n"
        "\n\ndef caller(base):\n    forward(base + '.run_manifest.json', {})\n",
    )
    counts, writers = census.scan(root)
    assert "COLLECT_PARSE_V3_23_0.py::forward" in writers
    assert counts["COLLECT_PARSE_V3_23_0.py::caller"] == 1
    assert census.resolved_site_classes(root)["COLLECT_PARSE_V3_23_0.py::caller"] == {"run-manifest"}


def test_a_passed_or_aliased_writer_is_still_a_write_site(tmp_path):
    root = _engine_tree(
        tmp_path,
        "\n\ndef emit(base, run):\n    run(write_json_file, base + '.snapshot.json', {})\n"
        "\n\ndef aliased(base):\n"
        "    from COLLECT_PARSE_V3_23_0 import write_json_file as publish\n"
        "    publish(base + '.snapshot.json', {})\n",
    )
    sites = census.write_sites(root)
    assert sites["COLLECT_PARSE_V3_23_0.py::emit"] == 1
    assert sites["COLLECT_PARSE_V3_23_0.py::aliased"] == 1


def test_a_row_must_name_every_class_its_sites_resolve_to(tmp_path):
    root = _engine_tree(
        tmp_path,
        "\n\ndef emit(base):\n    path = base + '.comparison.json'\n    write_json_file(path, {})\n",
    )
    rows = {**_BASE_ROW, "COLLECT_PARSE_V3_23_0.py::emit": (1, census.CLIENT, ("snapshot",), "x")}
    problems = census.census_problems(root, census=rows, registry_keys=["snapshot", "comparison-receipt"])
    assert problems == [
        "write site resolves to class 'comparison-receipt' its row does not name: "
        "COLLECT_PARSE_V3_23_0.py::emit"
    ]
    rows["COLLECT_PARSE_V3_23_0.py::emit"] = (1, census.NON_CLIENT, (), "x")
    assert any("comparison-receipt" in line for line in census.census_problems(
        root, census=rows, registry_keys=["comparison-receipt"]))


@pytest.mark.parametrize("name,problem", [
    ("delivery.snapshot.json", False), ("delivery.json", True), ("delivery", True), ("0", True),
])
def test_same_count_client_filename_replacement_is_rejected(tmp_path, name, problem):
    _write(tmp_path, "cisco_toolkit/writer.py",
           f"from pathlib import Path\n\ndef emit():\n    Path({name!r}).write_text('payload')\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("snapshot",), "client payload")}
    assert census.suffix_literals(tmp_path) == [], "bare filenames have no suffix-appending node"
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"])
    assert problems == ([f"client write site resolves to unclassified name {name!r}: "
                         "cisco_toolkit/writer.py::emit"] if problem else [])
    assert census.unclassified_site_literals(tmp_path) == (
        {"cisco_toolkit/writer.py::emit": {name}} if problem else {})


def test_partial_names_remain_uncertainty_and_known_formatted_literals_are_checked(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n"
           "def dynamic(stem):\n    Path(stem + '.txt').write_text('x')\n\n"
           "def fixed():\n    name = 'delivery.json'\n    Path(f'{name}').write_text('x')\n")
    rows = {"cisco_toolkit/writer.py::dynamic": (1, census.CLIENT, ("capture-show",), "collector-shaped input"),
            "cisco_toolkit/writer.py::fixed": (1, census.CLIENT, ("snapshot",), "client bytes")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["capture-show", "snapshot"]) == [
        "client write site resolves to unclassified name 'delivery.json': cisco_toolkit/writer.py::fixed"]
    assert census.unresolved_site_templates(tmp_path) == {"cisco_toolkit/writer.py::dynamic": {"0.txt"}}


def test_receipt_partial_extension_is_not_an_input_stem_suffix_obligation(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\ndef emit(extension):\n"
           "    original = Path('delivery.snapshot.json')\n"
           "    staged = f'.{original.stem}.receipt-0.previous{extension}'\n"
           "    Path(staged).write_text('payload')\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("receipt-previous-html",), "receipt staging")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["receipt-previous-html"]) == []
    assert census.unresolved_site_templates(tmp_path) == {
        "cisco_toolkit/writer.py::emit": {".0.receipt-0.previous0"}}


@pytest.mark.parametrize("marker_name", ["probe.marker", "delivery.json"])
@pytest.mark.parametrize("marker_first", [True, False])
def test_non_client_helper_provenance_does_not_erase_client_literal_refusal(tmp_path, monkeypatch,
                                                                        marker_name, marker_first):
    statements = [f"    marker({marker_name!r})\n", "    Path('delivery.json').write_text('payload')\n"]
    if not marker_first:
        statements.reverse()
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n"
           "def marker(path):\n    Path(path).write_bytes(b'ok')\n\n"
           "def main():\n" + "".join(statements))
    rows = {"cisco_toolkit/writer.py::marker": (1, census.NON_CLIENT, (), "fixed marker bytes only"),
            "cisco_toolkit/writer.py::main": (2, census.CLIENT, ("snapshot",), "client payload plus probe")}
    monkeypatch.setattr(census, "WRITE_SITE_CENSUS", rows)
    assert census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"]) == [
        "client write site resolves to unclassified name 'delivery.json': cisco_toolkit/writer.py::main"]
    assert census.unclassified_site_literals(tmp_path)["cisco_toolkit/writer.py::main"] == {
        "delivery.json", marker_name}


@pytest.mark.parametrize("expression,filename", [
    ("f'{name!r}'", "'delivery.snapshot.json'"), ("f'{7}.json'", "7.json"),
    ("f'{7:04d}.json'", "0007.json"),
])
def test_closed_formatted_literals_use_actual_conversion_and_format_spec(tmp_path, expression, filename):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\ndef emit():\n    name = 'delivery.snapshot.json'\n"
           f"    Path({expression}).write_text('payload')\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("snapshot",), "client payload")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"]) == [
        f"client write site resolves to unclassified name {filename!r}: cisco_toolkit/writer.py::emit"]


@pytest.mark.parametrize("filename,problem", [("client.db", False), ("client.json", True)])
def test_sqlite_uri_is_a_database_path_not_a_query_shaped_filename(tmp_path, filename, problem):
    _write(tmp_path, "cisco_toolkit/writer.py",
           f"import sqlite3\n\ndef emit():\n    sqlite3.connect('file:{filename}?mode=ro', uri=True)\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("database",), "may create client companions")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["database"]) == (
        [f"client write site resolves to unclassified name {filename!r}: cisco_toolkit/writer.py::emit"]
        if problem else [])


@pytest.mark.parametrize("disposition", [census.NON_CLIENT, census.OPERATOR_PATH, census.DELEGATED])
def test_unclassified_operator_and_non_client_names_stay_explicit(tmp_path, disposition):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\ndef emit(path):\n    Path(path or 'operator.json').write_text('x')\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, disposition, (), "caller/operator/non-client name")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=[]) == []
    assert census.unclassified_site_literals(tmp_path) == {"cisco_toolkit/writer.py::emit": {"operator.json"}}


@pytest.mark.parametrize("filename,problem", [("delivery.snapshot.json", False), ("delivery.json", True)])
@pytest.mark.parametrize("forward", ["phase(label, fn, *args, **kwargs)",
                                    "phase(label=label, fn=fn, target=args[0], payload=args[1])"])
def test_callback_projection_checks_targets_not_phase_or_payload_literals(tmp_path, filename, problem, forward):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n"
           "def write(target, payload):\n    Path(target).write_text(payload)\n\n"
           "def phase(label, fn, target, payload):\n    fn(target, payload)\n\n"
           f"def emit(label, kind, fn, *args, **kwargs):\n    {forward}\n\n"
           f"def main():\n    emit('HTML Explorer', 'html', write, {filename!r}, 'literal payload')\n")
    rows = {
        "cisco_toolkit/writer.py::write": (1, census.DELEGATED, (), "path writer"),
        "cisco_toolkit/writer.py::main": (1, census.CLIENT, ("snapshot",), "client data"),
    }
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"])
    assert problems == ([f"client write site resolves to unclassified name {filename!r}: "
                         "cisco_toolkit/writer.py::main"] if problem else [])
    assert census.unclassified_site_literals(tmp_path) == (
        {"cisco_toolkit/writer.py::main": {filename}} if problem else {})


def test_default_target_literal_is_resolved_in_its_defining_module(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\nDEFAULT_PATH = 'delivery.json'\n\n"
           "def write(path=DEFAULT_PATH):\n    Path(path).write_text('payload')\n")
    _write(tmp_path, "cisco_toolkit/caller.py",
           "from cisco_toolkit.writer import write\nDEFAULT_PATH = 'safe.snapshot.json'\n\n"
           "def emit():\n    write()\n")
    rows = {"cisco_toolkit/writer.py::write": (1, census.DELEGATED, (), "writer"),
            "cisco_toolkit/caller.py::emit": (1, census.CLIENT, ("snapshot",), "client data")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"]) == [
        "client write site resolves to unclassified name 'delivery.json': cisco_toolkit/caller.py::emit"]


def test_guarded_out_of_range_variadic_target_does_not_hide_alternative(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n"
           "def write(path):\n    Path(path).write_text('payload')\n\n"
           "def emit(fn, *args):\n"
           "    if args:\n        fn(args[0])\n"
           "    else:\n        fn('delivery.json')\n\n"
           "def main():\n    emit(write)\n")
    rows = {"cisco_toolkit/writer.py::write": (1, census.DELEGATED, (), "writer"),
            "cisco_toolkit/writer.py::main": (1, census.CLIENT, ("snapshot",), "client data")}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"]) == [
        "client write site resolves to unclassified name 'delivery.json': cisco_toolkit/writer.py::main"]


@pytest.mark.parametrize("suffix,problem", [(".tmp", False), (".json", True)])
def test_temporary_names_compose_prefix_and_suffix_without_classifying_directory(tmp_path, suffix, problem):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "import tempfile\n\ndef emit(directory):\n"
           f"    tempfile.mkstemp(dir=directory or '.', prefix='delivery.', suffix={suffix!r})\n")
    rows = {"cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("atomic-staging",), "client staging")}
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["atomic-staging"])
    assert problems == (["client write site resolves to unclassified name 'delivery.0.json': "
                         "cisco_toolkit/writer.py::emit"] if problem else [])
    assert "cisco_toolkit/writer.py::emit" in census.scan(tmp_path)[1], "directory flow must be retained"


def test_a_second_write_in_a_classified_function_and_a_vanished_row_fail_the_census(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n\ndef emit(path):\n"
           "    Path(path).write_text('a')\n    open(path + '.log', 'a')\n")
    rows = {
        "cisco_toolkit/writer.py::emit": (1, census.DELEGATED, ("engine-log",), "x"),
        "cisco_toolkit/writer.py::gone": (1, census.NON_CLIENT, (), "x"),
    }
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["engine-log"])
    assert problems == [
        "census row has no write site any more: cisco_toolkit/writer.py::gone",
        "write count changed: cisco_toolkit/writer.py::emit census=1 observed=2",
    ]


def test_census_rows_must_name_registered_classes_and_real_delegation(tmp_path):
    _write(tmp_path, "portable/tool.py",
           "def emit():\n    open('fixed.txt', 'w')\n\n\ndef helper():\n    open('other.txt', 'w')\n")
    rows = {
        "portable/tool.py::emit": (1, census.CLIENT, ("not-a-class",), "x"),
        "portable/tool.py::helper": (1, census.DELEGATED, (), "x"),
    }
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"])
    assert "write site names an unregistered class 'not-a-class': portable/tool.py::emit" in problems
    assert "delegated row is not a path-parameter writer: portable/tool.py::helper" in problems
    rows = {"portable/tool.py::emit": (1, census.CLIENT, (), " "),
            "portable/tool.py::helper": (1, "maybe", (), "x")}
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"])
    assert "client write site names no registry class: portable/tool.py::emit" in problems
    assert "census row gives no reason: portable/tool.py::emit" in problems
    assert "unknown disposition 'maybe': portable/tool.py::helper" in problems


def test_module_aliases_name_imports_and_computed_flags_are_write_sites(tmp_path):
    _write(tmp_path, "cisco_toolkit/aliases.py",
           "import os as _os\nimport logging.handlers\nfrom shutil import copy2\n"
           "from zipfile import ZipFile\nfrom pathlib import Path\n\n\n"
           "def a(src, dst):\n    _os.replace(src, dst)\n\n\n"
           "def b(src, dst):\n    copy2(src, dst)\n\n\n"
           "def c(dst):\n    ZipFile(dst, 'w')\n\n\n"
           "def d(dst):\n    logging.handlers.RotatingFileHandler(dst)\n\n\n"
           "def e(dst, flags):\n    _os.open(dst, flags)\n\n\n"
           "def f(dst):\n    Path('tmp').replace(dst)\n\n\n"
           "def g(dst, mode):\n    Path(dst).open(mode)\n\n\n"
           "def h(dst):\n    flags = _os.O_RDONLY | getattr(_os, 'O_BINARY', 0)\n    _os.open(dst, flags)\n")
    sites = census.write_sites(tmp_path)
    for name in "abcdefg":
        assert sites.get(f"cisco_toolkit/aliases.py::{name}") == 1, name
    # Negative control: a flag set that resolves to read-only flags is not a write.
    assert "cisco_toolkit/aliases.py::h" not in sites


@pytest.mark.parametrize("source", [
    "open(p, 'w')", "open(p, 'ab')", "open(p, mode)", "open(p, mode='x')", "p.open('xb')",
    "p.open(mode='w')", "os.open(p, os.O_RDWR | os.O_CREAT)", "os.open(p, flags)",
    "zipfile.ZipFile(p, 'w')", "tempfile.mkstemp()", "tempfile.NamedTemporaryFile(delete=False)",
    "sqlite3.connect(p)", "shutil.copy2(a, b)", "shutil.copytree(a, b)", "shutil.make_archive(a, 'zip')",
    "shutil.unpack_archive(a, b)", "os.replace(a, b)", "doc.save(p)", "p.write_bytes(b)",
    "p.write_text(t)", "logging.FileHandler(p)", "logging.basicConfig(filename=p)",
    "gzip.open(p, 'wb')", "io.FileIO(p, 'w')", "gzip.GzipFile(p, 'wb')", "p.replace(q)",
    "p.rename(q)", "p.hardlink_to(q)", "p.symlink_to(q)", "zf.extractall(d)", "frame.to_csv(p)",
    "figure.savefig(p)", "urllib.request.urlretrieve(u, p)",
    "connection.execute('VACUUM INTO ?', (p,))",
])
def test_write_primitives_are_recognised(source):
    assert census.write_primitive(ast.parse(source, mode="eval").body) is not None


@pytest.mark.parametrize("source", [
    "open(p)", "open(p, 'rb')", "p.open()", "p.open('rb')", "zf.open(info)",
    "opener.open(urllib.request.Request(url), timeout=5)", "zipfile.ZipFile(p)",
    "tarfile.open(p, 'r:gz')", "os.open(p, os.O_RDONLY)", "os.makedirs(d)", "Path(d).mkdir()",
    "text.replace('a', 'b')", "current.copy()", "value.replace(tzinfo=zone)",
    "logging.basicConfig(level=logging.INFO)", "connection.execute('SELECT 1')",
])
def test_reads_directory_creation_and_lookalikes_are_not_write_sites(source):
    assert census.write_primitive(ast.parse(source, mode="eval").body) is None


@pytest.mark.parametrize("statement,literal", [
    ("name = base + '-x.json'", "-x.json"),
    ("name = f'{base}-x.json'", "-x.json"),
    ("name = '%s.x.json' % base", ".x.json"),
    ("name = '{}.x.json'.format(base)", ".x.json"),
    ("name = path.with_suffix('.x.json')", ".x.json"),
    ("name = ''.join([base, '.x.json'])", ".x.json"),
])
def test_every_suffix_shape_is_collected(tmp_path, statement, literal):
    _write(tmp_path, "cisco_toolkit/shapes.py", f"def f(base, path):\n    {statement}\n")
    assert [lit for _location, lit in census.suffix_literals(tmp_path)] == [literal]


def test_non_client_suffix_declarations_are_keyed_by_file(tmp_path):
    _write(tmp_path, "portable/release.py", "def f(b):\n    return b + '.manifest.json'\n")
    _write(tmp_path, "COLLECT_PARSE_V3_23_0.py", "def g(b):\n    return b + '.manifest.json'\n")
    allowed = {("portable/release.py", ".manifest.json"): "release metadata"}
    problems = census.suffix_literal_problems(tmp_path, non_client=allowed)
    assert problems == ["unclassified output-name suffix literal '.manifest.json' at "
                        "COLLECT_PARSE_V3_23_0.py:2"]


# ---------------------------------------------------------------- one registry, two gates


def test_the_repository_gate_restates_the_owner_registry_exactly():
    gate = _repository_gate()
    assert tuple(gate._CLIENT_ARTIFACT_NAME_CLASSES) == CLASSES
    assert gate._CLIENT_ARTIFACT_EXCEPTIONS == dv.CLIENT_ARTIFACT_EXCEPTIONS
    assert gate._CLIENT_FIXTURE_EXEMPTIBLE_CLASSES == dv.CLIENT_FIXTURE_EXEMPTIBLE_CLASSES
    assert gate._CLIENT_FIXTURE_MANIFEST.as_posix() == dv.CLIENT_FIXTURE_MANIFEST
    assert gate._CLIENT_NAME_STRIP == dv._CLIENT_NAME_STRIP


def _differential_corpus() -> list[str]:
    rng = random.Random(65)
    pieces = [pattern for _key, _match, pattern in CLASSES] + [
        ".txt", ".json", ".html", "show", "Acme", "tests/", "TESTS/", "tests\\fixtures\\", "/",
        "\\", ".", " ", "​", "ｄｏｃｘ", "ſ", "-", "_", "x",
    ]
    corpus = set()
    for key, match, pattern in CLASSES:
        probe = _probe(match, pattern)
        corpus.update({probe, probe.upper(), probe.title(), probe.replace("/", "\\"), probe + ".",
                       probe + " ", "tests/fixtures/" + probe.rsplit("/", 1)[-1],
                       "TESTS/fixtures/" + probe.rsplit("/", 1)[-1]})
    for exception in dv.CLIENT_ARTIFACT_EXCEPTIONS:
        corpus.update({exception, exception.upper(), exception + ".", "x/" + exception})
    for _ in range(4000):
        corpus.add("".join(rng.choice(pieces) for _ in range(rng.randint(1, 5))))
    return sorted(corpus)


def test_the_two_matchers_agree_on_a_generated_corpus_and_every_tracked_path():
    """Behavioural parity, not just equal data: a semantic edit to one restated matcher fails."""
    gate = _repository_gate()
    paths = _differential_corpus() + _tracked()
    disagreements = [p for p in paths if dv.client_artifact_class(p) != gate._client_artifact_class(p)]
    assert disagreements == []
    assert len(paths) > 4000


def test_the_registry_is_well_formed(monkeypatch):
    keys = [key for key, _match, _pattern in CLASSES]
    assert len(keys) == len(set(keys)), "registry keys must be unique"
    assert len({pattern.casefold() for _key, _match, pattern in CLASSES}) == len(CLASSES)
    assert {match for _key, match, _pattern in CLASSES} <= set(dv.CLIENT_ARTIFACT_MATCHES)
    assert all(producer.strip() for *_row, producer in dv.CLIENT_ARTIFACT_NAME_CLASSES)
    assert dv._FORBIDDEN_SUFFIXES == tuple(p for _k, m, p in CLASSES if m == "suffix")
    assert dv.CLIENT_FIXTURE_EXEMPTIBLE_CLASSES <= set(keys)
    # Negative control: an unknown match kind fails closed instead of matching nothing.
    monkeypatch.setattr(dv, "_CLIENT_ARTIFACT_FOLDED", (("bad", "glob", "*"),))
    with pytest.raises(ValueError, match="unknown client-artifact match"):
        dv.client_artifact_class("customer-output/anything")


@pytest.mark.parametrize("key,match,pattern", CLASSES, ids=[row[0] for row in CLASSES])
def test_both_gates_refuse_every_class_and_name_the_same_class(key, match, pattern):
    gate = _repository_gate()
    probe = _probe(match, pattern)
    assert dv.client_artifact_class(probe) == key
    assert gate._client_artifact_class(probe) == key
    assert dv._privacy_violations({probe}) == [probe]
    for variant in (probe.upper(), probe + ".", probe + " ", probe + "​"):
        assert dv.client_artifact_class(variant) == key, variant
        assert gate._client_artifact_class(variant) == key, variant


def test_width_and_compatibility_variants_still_classify():
    for variant in ("out/Acme.ｄｏｃｘ", "out/Acme.docx​.", "out/Acme.docx\n",
                    "out/ACME.ſnapshot.json"):
        assert dv.client_artifact_class(variant) is not None, variant
        assert _repository_gate()._client_artifact_class(variant) is not None, variant


@pytest.mark.parametrize("path", [
    "cisco_toolkit/html.py", "README.md", "docs/ssot.md", "webapp/frontend/dist/index.html",
    "tests/golden/snapshot.json", "cisco_toolkit/data/atlas-r1-retrospective-comparison.json",
    "cisco_toolkit/data/registry_manifest.json", "docs/quality/scorecard.jsonl",
    *sorted(dv.CLIENT_ARTIFACT_EXCEPTIONS),
])
def test_ordinary_source_and_reviewed_exceptions_pass_both_gates(path):
    gate = _repository_gate()
    assert dv.client_artifact_class(path) is None
    assert gate._client_artifact_class(path) is None
    if not any(part in dv._FORBIDDEN_PARTS for part in PurePosixPath(path).parts):
        assert dv._privacy_violations({path}) == []


def test_exceptions_are_exact_paths():
    for exception in dv.CLIENT_ARTIFACT_EXCEPTIONS:
        assert dv.client_artifact_class("copy/" + exception) is not None
        assert dv.client_artifact_class(exception.upper()) is not None


def test_the_csv_exceptions_are_exactly_the_retained_official_sources():
    manifest = json.loads((ROOT / "reference-data/official-sources/manifest.json").read_text(encoding="utf-8"))
    paths = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "path" and isinstance(item, str):
                    paths.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(manifest)
    official_csv = {path for path in paths if path.endswith(".csv")}
    assert len(official_csv) == 4
    exempt_csv = {path for path in dv.CLIENT_ARTIFACT_EXCEPTIONS if path.endswith(".csv")}
    assert exempt_csv == official_csv


# ---------------------------------------------------------------- the raw-capture owner


#: The raw owner's open class also includes ordinary text and extension-less repository names.
_CONTEXT_ONLY = ("notes.txt", "README", "Makefile", "output")
#: Known difference: portable excludes ZIPs by container context; the global registry cannot.
_BUNDLE_CONTEXT_ONLY = {".zip": "generic ZIPs also contain public product/distribution material"}


def _bundle_owner_corpus(source: str, owner=bundle_client_name) -> set[str]:
    shapes = census.bundle_artifact_name_shapes(source)
    names = {_probe(match, pattern).rsplit("/", 1)[-1] for match, pattern in shapes}
    suffixes = {pattern for match, pattern in shapes if match == "suffix"}
    stems = {"probe"} | {pattern + "probe" for match, pattern in shapes if match == "leaf-prefix"}
    stems |= {"CORE-1" + pattern for match, pattern in shapes if match == "contains"}
    names |= {stem + suffix for stem in stems for suffix in suffixes}
    accepted = {name for name in names if owner(f"site/{name}")}
    for match, pattern in shapes:
        witnesses = {name for name in accepted if (
            name.endswith(pattern) if match == "suffix" else
            name == pattern if match == "leaf" else
            name.startswith(pattern) if match == "leaf-prefix" else pattern in name
        )}
        assert witnesses, f"bundle shape {match}:{pattern} has no owner-accepted witness"
    return accepted


def test_the_registry_reconciles_with_the_raw_capture_owner_both_ways():
    owner = _raw_capture_owner()
    gate = _repository_gate()
    source = (ROOT / "portable/release_contract.py").read_text(encoding="utf-8")
    names = _bundle_owner_corpus(source)
    assert names, "bundle owner supplied no positive name shape"
    seen_context = set()
    for name in names:
        if Path(name).suffix in _BUNDLE_CONTEXT_ONLY:
            seen_context.add(Path(name).suffix)
            continue
        expected = dv.client_artifact_class(f"site/{name}")
        assert expected is not None, f"bundle owner name {name} has no registry class"
        assert gate._client_artifact_class(f"site/{name}") == expected
        # The live raw owner decides capture vs structured artifact; derive its excluded
        # suffixes from that same owner instead of restating selected class keys.
        assert bool(owner(name)) == (Path(name).suffix.casefold() in {
            *owner.__globals__["_STRUCTURED_CAPTURE_SUFFIXES"], owner.__globals__["_SCRUB_TEMP_SUFFIX"]
        })
    assert seen_context == set(_BUNDLE_CONTEXT_ONLY), "a documented bundle-only shape disappeared"
    # Registry -> raw owner for actual capture/configuration selectors, including shapes the
    # bundle does not yet own (.out and -confg). No finite corpus stands in for the open class.
    for key, match, pattern in CLASSES:
        if match in {"capture", "contains"}:
            leaf = _probe(match, pattern).rsplit("/", 1)[-1]
            assert owner(leaf) == "", f"{key} claims {leaf}, which the owner does not call a capture"
    for suffix in {*owner.__globals__["_STRUCTURED_CAPTURE_SUFFIXES"], owner.__globals__["_SCRUB_TEMP_SUFFIX"]}:
        assert owner(f"capture{suffix}"), f"raw owner exclusion {suffix} became a capture"
    # Context-only owner captures: named here, and deliberately not name classes.
    for name in _CONTEXT_ONLY:
        assert owner(name) == ""
        assert dv.client_artifact_class(f"site/{name}") is None


def test_bundle_owner_shape_additions_are_derived_and_unregistered_shapes_refused():
    source = (ROOT / "portable/release_contract.py").read_text(encoding="utf-8")
    changed = source.replace('".db", ".sqlite",', '".new-capture", ".db", ".sqlite",', 1)
    assert changed != source
    shapes = census.bundle_artifact_name_shapes(changed)
    assert ("suffix", ".new-capture") in shapes
    assert dv.client_artifact_class("site/probe.new-capture") is None
    assert _repository_gate()._client_artifact_class("site/probe.new-capture") is None
    with pytest.raises(ValueError, match="unrecognised bundle client-name selector"):
        census.bundle_artifact_name_shapes(
            "def _forbidden_client_artifact(relative):\n    return custom_selector(relative)\n")


def test_every_collector_capture_filename_is_a_registered_capture_class():
    def offline_name(command: str) -> str:
        return command.replace(" ", "_").replace("|", "_").replace("^", "").replace("/", "_") + ".txt"

    names = set()
    engine = ast.parse((ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8"))
    for node in engine.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith("COMMANDS_")):
            try:
                commands = ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue  # the computed COMMANDS_ALL union of the literal lists
            names.update(offline_name(command) for command in commands)
    rest = ast.parse((ROOT / "cisco_toolkit" / "rest_collect.py").read_text(encoding="utf-8"))
    rest_names = set()
    for node in ast.walk(rest):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.endswith(("_CLASSES", "_ENDPOINTS"))
                and isinstance(node.value, ast.Dict)):
            rest_names.update(offline_name(key.value) for key in node.value.keys
                              if isinstance(key, ast.Constant) and isinstance(key.value, str))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_write" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)):
            rest_names.add(offline_name(node.args[1].value))
    assert len(names) >= 100 and len(rest_names) >= 15, (len(names), len(rest_names))
    unregistered = sorted(
        name for name in names | rest_names
        if not (dv.client_artifact_class(f"customer-output/CORE-1/{name}") or "").startswith(
            ("capture-", "config-name-"))
    )
    assert unregistered == []


# ---------------------------------------------------------------- producer names -> registry


def test_every_docmeta_artifact_name_is_a_registered_class():
    names = set()
    for spec in docmeta.ARTIFACT_SPECS:
        names.update(suffix for suffix in (spec.cli_suffix, spec.assesshub_suffix) if suffix)
    assert len(names) >= 10
    missing = sorted(s for s in names if dv.client_artifact_class(f"customer-output/Acme{s}") is None)
    assert missing == []
    candidates = docmeta.artifact_candidate_paths(os.path.join("customer-output", "Acme"))
    assert len(candidates) >= len(docmeta.CLI_ARTIFACT_SUFFIX) + 5
    leaves = sorted(os.path.basename(path) for path in candidates)
    assert [leaf for leaf in leaves if dv.client_artifact_class(f"customer-output/{leaf}") is None] == []


def _module_string_constants(relative: str) -> dict[str, str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
    found = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    return found


def test_named_producer_constants_are_registered_classes():
    ingest = _module_string_constants("webapp/backend/ingest.py")
    capture = _module_string_constants("cisco_toolkit/capture_integrity.py")
    names = {
        "ingest._REDACTION_RECEIPT": ingest["_REDACTION_RECEIPT"],
        "ingest.UNSAFE_MARKER": ingest["UNSAFE_MARKER"],
        "ingest._INCOMPLETE_MARKER": ingest["_INCOMPLETE_MARKER"],
        "ingest._INCOMPLETE_FALLBACK": ingest["_INCOMPLETE_FALLBACK"],
        "capture_integrity.CAPTURE_META_FILENAME": capture["CAPTURE_META_FILENAME"],
        "gate_state.STORE_RELPATH": os.path.basename(gate_state.STORE_RELPATH),
        "recall.QUERY_LOG_PATH": os.path.basename(recall.QUERY_LOG_PATH),
        "engine_log_path": os.path.basename(
            engine_log_path(frozen=False, executable="x", cwd=".", version="1.2.3")),
    }
    unregistered = {owner: name for owner, name in names.items()
                    if dv.client_artifact_class(f"customer-output/{name}") is None}
    assert unregistered == {}


def test_every_browser_download_name_classifies():
    """SPA, Scope and engine explorer downloads must classify in both matchers."""
    names = census.download_names(ROOT)
    assert len(names) >= 15, names
    gate = _repository_gate()
    problems = []
    for location, expression, template in names:
        relative = location.rsplit(":", 1)[0]
        if template is None:
            if (relative, expression) not in census.DOWNLOAD_NAME_PASSTHROUGH:
                problems.append(f"undeclared non-literal download name {expression!r} at {location}")
        else:
            artifact_class = dv.client_artifact_class(f"Downloads/{template}")
            if artifact_class is None:
                problems.append(f"download name {template!r} at {location} matches no class")
            assert gate._client_artifact_class(f"Downloads/{template}") == artifact_class
    assert problems == []
    used = {(location.rsplit(":", 1)[0], expression) for location, expression, _t in names}
    assert set(census.DOWNLOAD_NAME_PASSTHROUGH) <= used, "a declared pass-through no longer exists"
    classes = {dv.client_artifact_class(f"Downloads/{t}") for _l, _e, t in names if t}
    assert {"protocol-assurance-export", "comparison-receipt", "trend-comparisons",
            "scope-record-export"} <= classes
    assert {path for path in _tracked() if path.startswith("cisco_toolkit/") and path.endswith(".html")} <= set(
        census.download_sources(ROOT))


def test_engine_html_download_discovery_includes_nested_calls_and_unknown_names(tmp_path):
    _write(tmp_path, "cisco_toolkit/new-explorer.html",
           '<a download="flow-frames.txt">export</a>\n'
           '<script>\n'
           'downloadBlob(new Blob([payload], {type: "text/plain"}), "flow-path.svg");\n'
           'downloadBlob(blob, "ipv6-routing-blockers-" + scope + ".json");\n'
           'downloadBlob(blob, "unregistered.json");\n'
           'a.download = unknown;\n'
           '</script>\n')
    names = census.download_names(tmp_path)
    assert {template for _location, _expression, template in names} == {
        "flow-frames.txt", "flow-path.svg", "ipv6-routing-blockers-0.json", "unregistered.json", None}
    for template in ("flow-frames.txt", "flow-path.svg", "ipv6-routing-blockers-0.json"):
        assert dv.client_artifact_class(f"Downloads/{template}") is not None
        assert _repository_gate()._client_artifact_class(f"Downloads/{template}") is not None
    assert dv.client_artifact_class("Downloads/unregistered.json") is None
    assert ("cisco_toolkit/new-explorer.html", "unknown") not in census.DOWNLOAD_NAME_PASSTHROUGH


def test_engine_html_attribute_forms_and_implicit_names_are_not_silently_skipped(tmp_path):
    _write(tmp_path, "cisco_toolkit/explorer.html",
           '<a download=topology.svg></a>\n<a href="data.json" download></a>\n'
           '<script>a.setAttribute("download", "flow-frames.txt");</script>\n')
    names = census.download_names(tmp_path)
    assert {template for _location, _expression, template in names} == {
        "topology.svg", "flow-frames.txt", None}
    assert any(expression == "<implicit browser filename>" for _location, expression, _template in names)


def test_commented_optional_calls_and_bracket_download_properties_are_discovered(tmp_path):
    _write(tmp_path, "cisco_toolkit/explorer.html",
           '<script>downloadBlob /* reason */ (blob, "unknown.json");\n'
           'downloadBlob?.(blob, "unknown.json");\n'
           'a["download"] = "unknown.json";</script>\n')
    names = census.download_names(tmp_path)
    assert len(names) == 3
    assert all(template == "unknown.json" for _location, _expression, template in names)
    assert dv.client_artifact_class("Downloads/unknown.json") is None


def test_the_comparison_download_suffix_is_the_registered_class():
    source = (ROOT / "webapp/frontend/src/components/ComparisonDecision.tsx").read_text(encoding="utf-8")
    match = re.search(r'export const COMPARISON_RECEIPT_SUFFIX = "([^"]+)";', source)
    assert match and dv.client_artifact_class(f"x/a{match.group(1)}") == "comparison-receipt"


def test_download_name_extraction_rejects_an_unclassified_name(tmp_path):
    _write(tmp_path, "webapp/frontend/src/pages/Bad.tsx",
           "export const A = () => <a download={`receipt-${id}.json`}>x</a>;\n"
           "downloadJsonDocument(doc, `atlas-${id}.trend-comparisons.json`);\n")
    _write(tmp_path, "webapp/frontend/src/pages/Bad.test.tsx", "<a download=\"ignored.json\" />\n")
    names = census.download_names(tmp_path)
    assert [(e, t) for _l, e, t in names] == [
        ("`receipt-${id}.json`", "receipt-0.json"),
        ("`atlas-${id}.trend-comparisons.json`", "atlas-0.trend-comparisons.json"),
    ]
    assert dv.client_artifact_class("Downloads/receipt-0.json") is None


def test_every_backend_content_disposition_name_classifies():
    names = census.response_filenames(ROOT)
    assert any(t and t.endswith(".protocol-assurance.json") for _f, _l, t in names), names
    for function, location, template in names:
        if template is None:
            assert function == "webapp/backend/app.py::_send_file", (function, location)
        else:
            assert dv.client_artifact_class(f"Downloads/{template}") is not None, (location, template)
    # _send_file's name is "<label><suffix>": every caller passes a registry-owned download suffix.
    tree = ast.parse((ROOT / "webapp/backend/app.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "_send_file"]
    assert calls
    for call in calls:
        suffix = call.args[3] if len(call.args) > 3 else None
        assert isinstance(suffix, ast.Attribute) and suffix.attr == "download_suffix", ast.unparse(call)
    for spec in docmeta.ARTIFACT_SPECS:
        if spec.assesshub_suffix:
            assert dv.client_artifact_class(f"Downloads/x{spec.download_suffix}") is not None


def test_the_powershell_backup_writer_builds_only_registered_database_names():
    names = census.powershell_database_names(ROOT)
    assert len(names) >= 3, names
    unregistered = [(loc, t) for loc, t in names
                    if dv.client_artifact_class(f"release-backups/{t}") not in {"database",
                                                                                 "database-backup-partial"}]
    assert unregistered == []
    assert any(t.endswith(".db.partial") for _l, t in names)


# ---------------------------------------------------------------- registry -> .gitignore, tree


def _ignored(paths: list[str]) -> set[str]:
    proc = subprocess.run(
        [_git(), "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        input=b"".join(path.encode("utf-8") + b"\x00" for path in paths),
        capture_output=True,
        check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return {p.decode("utf-8").replace("\\", "/") for p in proc.stdout.split(b"\x00") if p}


def test_gitignore_carries_the_exact_generated_block():
    block = census.gitignore_block_in((ROOT / ".gitignore").read_text(encoding="utf-8"))
    assert block == census.gitignore_block(), "regenerate with tests/client_artifact_census.py :: gitignore_block"
    # Negative control: the extractor refuses a missing or duplicated block.
    assert census.gitignore_block_in("") is None
    assert census.gitignore_block_in(block + block) is None


def test_gitignore_ignores_every_registered_class_in_any_case():
    probes = []
    for _key, match, pattern in CLASSES:
        probe = _probe(match, pattern)
        directory, leaf = probe.rsplit("/", 1)
        probes += [probe, f"{directory}/{leaf.upper()}", f"{directory}/{leaf.swapcase()}"]
    missing = sorted(set(probes) - _ignored(probes))
    assert missing == [], f"client artifact names a `git add -A` would stage: {missing}"


def test_gitignore_keeps_the_reviewed_exceptions_and_fixtures_visible():
    visible = sorted(dv.CLIENT_ARTIFACT_EXCEPTIONS) + ["tests/fixtures/show_version.txt"]
    assert _ignored(visible) == set()
    assert _ignored(["customer-output/Acme.comparison.json"]) == {"customer-output/Acme.comparison.json"}


def _fixture_manifest() -> dict[str, str]:
    return _repository_gate()._parse_capture_fixture_manifest(
        (ROOT / dv.CLIENT_FIXTURE_MANIFEST).read_bytes())


def test_tracked_class_members_are_exactly_the_reviewed_fixtures():
    """No tracked file is a client class except a digest-pinned, reviewed synthetic fixture."""
    gate = _repository_gate()
    tracked = _tracked()
    assert len(tracked) > 1000, "the index looks wrong; this check would be vacuous"
    members = {path: gate._client_artifact_class(path) for path in tracked}
    members = {path: key for path, key in members.items() if key is not None}
    manifest = _fixture_manifest()
    assert set(members) == set(manifest), (sorted(set(members) - set(manifest)), sorted(set(manifest) - set(members)))
    assert manifest, "no reviewed fixture is listed; the exemption would be vacuous"
    for path, key in members.items():
        assert path.startswith("tests/fixtures/") and key in dv.CLIENT_FIXTURE_EXEMPTIBLE_CLASSES, (path, key)
        committed = subprocess.run([_git(), "show", f"HEAD:{path}"], cwd=ROOT, check=True,
                                   capture_output=True).stdout
        assert hashlib.sha256(committed.replace(b"\r\n", b"\n")).hexdigest() == manifest[path], path


def test_the_fixture_manifest_parser_fails_closed():
    parse = _repository_gate()._parse_capture_fixture_manifest
    digest = "a" * 64
    assert parse(f"# comment\n{digest}  tests/fixtures/x/show_a.txt\n".encode()) == {
        "tests/fixtures/x/show_a.txt": digest}
    for bad in (f"{digest}  docs/show_a.txt", f"{digest} tests/fixtures/a.txt", "zz  tests/fixtures/a.txt",
                f"{digest}  tests/fixtures/a.txt\n{digest}  tests/fixtures/a.txt"):
        with pytest.raises(ValueError):
            parse(bad.encode())


# ----------------------------------------------------------- W65b round-2 adversarial controls

@pytest.mark.parametrize("database", ["assesshub.db", "assesshub.sqlite", "assesshub.sqlite3",
                                      "operator-chosen", "custom.evidence", ".backup.db.partial"])
@pytest.mark.parametrize("companion,key", [("-wal", "database-wal"), ("-shm", "database-shm"),
                                          ("-journal", "database-journal")])
def test_sqlite_companions_cover_every_opened_database_name(database, companion, key, monkeypatch):
    name = "site/" + database + companion
    gate = _repository_gate()
    assert dv.client_artifact_class(name) == gate._client_artifact_class(name) == key
    assert dv._privacy_violations({name}) == [name]
    # Negative control: restoring the extension-bound selector loses alternate/staging names.
    narrowed = tuple((k, m, ".db" + companion if k == key else p)
                     for k, m, p in dv._CLIENT_ARTIFACT_FOLDED)
    monkeypatch.setattr(dv, "_CLIENT_ARTIFACT_FOLDED", narrowed)
    if not database.endswith(".db"):
        assert dv.client_artifact_class(name) is None


def test_storage_companion_owner_is_delete_and_has_no_attached_database_family():
    tree = ast.parse((ROOT / "webapp/backend/storage.py").read_text(encoding="utf-8"))
    sql = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "PRAGMA journal_mode = DELETE" in sql
    # SQLite super-journals need ATTACH/multiple databases. The storage owner never attaches;
    # its main/backup (including arbitrary names and .partial) connections are tied above.
    assert not any(re.match(r"\s*ATTACH\b", statement, re.I) for statement in sql)
    mutated = sql + ["ATTACH DATABASE 'alternate' AS other"]
    assert any(re.match(r"\s*ATTACH\b", statement, re.I) for statement in mutated)


@pytest.mark.parametrize("expression,leaf", [
    ('"delivery.json".format()', "delivery.json"),
    ('"{}".format("delivery.json")', "delivery.json"),
    ('"{leaf}".format(leaf="delivery.json")', "delivery.json"),
    ('"%s" % "delivery.json"', "delivery.json"),
    ('"%(leaf)s" % {"leaf": "delivery.json"}', "delivery.json"),
    ('"{:04d}.json".format(7)', "0007.json"),
    ('"%04d.json" % 7', "0007.json"),
    ('"{!r}.json".format("client")', "'client'.json"),
    ('"{}".format("private" + ".json")', "private.json"),
    ('"{}".format(*("private.json",))', "private.json"),
    ('"{leaf}".format(**{"leaf": "private.json"})', "private.json"),
    ('"%s" % ("private" + ".json")', "private.json"),
    ('"%*s" % (3, "private.json")', "private.json"),
    ('"%.*s" % (7, "private.json")', "private"),
    ('"{}".format("%s" % "private.json")', "private.json"),
    ('"{0}".format("private.json", dynamic())', "private.json"),
    ('"{1}".format(dynamic(), "private.json")', "private.json"),
    ('"{}".format("PRIVATE.JSON".lower())', "private.json"),
    ('"{}".format(f"private.json")', "private.json"),
    ('"%s" % f"private.json"', "private.json"),
    ('"{}".format({"leaf": "private.json"}["leaf"])', "private.json"),
    ('"{0[0]}".format(("private.json", dynamic()))', "private.json"),
    ('"{0[leaf]}".format({"leaf": "private.json", "unused": dynamic()})', "private.json"),
    ('"%(leaf)s" % {"leaf": "private.json", "unused": dynamic()}', "private.json"),
    ('"private%%(leaf)s.json" % {"unused": dynamic()}', "private%(leaf)s.json"),
    ('"{}".format("private.json"[:7])', "private"),
    ('"%s" % "private.json"[:7]', "private"),
])
def test_closed_format_and_percent_targets_cannot_escape_client_refusal(tmp_path, expression, leaf):
    _write(tmp_path, "cisco_toolkit/writer.py", "from pathlib import Path\n\ndef emit():\n"
           + f"    Path({expression}).write_text('payload')\n")
    key = "cisco_toolkit/writer.py::emit"
    rows = {key: (1, census.CLIENT, ("snapshot",), "client payload")}
    assert census.unclassified_site_literals(tmp_path)[key] == {leaf}
    assert census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"]) == [
        f"client write site resolves to unclassified name {leaf!r}: {key}"]


def test_seventeenth_and_literal_loop_names_are_not_discarded(tmp_path):
    assignments = "".join(f"    name = 'safe{i}.snapshot.json'\n" for i in range(16))
    _write(tmp_path, "cisco_toolkit/writer.py", "from pathlib import Path\n\ndef emit():\n"
           + assignments + "    name = 'private.json'\n    Path(name).write_text('payload')\n"
           + "\ndef loop():\n    for name in ['safe.snapshot.json', 'private-loop.json']:\n"
           + "        Path(name).write_text('payload')\n")
    rows = {f"cisco_toolkit/writer.py::{fn}": (1, census.CLIENT, ("snapshot",), "client payload")
            for fn in ("emit", "loop")}
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"])
    assert any("'private.json'" in p for p in problems)
    assert any("'private-loop.json'" in p for p in problems)


@pytest.mark.parametrize("kind", ["alternatives", "depth"])
def test_filename_model_bound_is_a_refusal_not_success(kind):
    if kind == "alternatives":
        node = ast.Name(id="target")
        values = [ast.Constant(value=f"safe{i}.snapshot.json") for i in range(census._NAME_ALTERNATIVES)]
        values.append(ast.Constant(value="private.json"))
        def resolver(_name):
            return values
    else:
        def resolver(_name):
            index = int(_name.id.removeprefix("target"))
            return [ast.Name(id=f"target{index + 1}")]
        node = ast.Name(id="target0")
    with pytest.raises(census.NameModelLimit, match="filename model"):
        census._templates(node, resolver)


@pytest.mark.parametrize("expression", ["f'{name}'", "'{}'.format(name)", "'%s' % name"])
def test_unknown_format_alternative_keeps_the_concrete_bad_name(tmp_path, expression):
    _write(tmp_path, "cisco_toolkit/writer.py", "from pathlib import Path\n\ndef emit():\n"
           "    name = dynamic()\n    name = 'private.json'\n"
           + f"    Path({expression}).write_text('payload')\n")
    key = "cisco_toolkit/writer.py::emit"
    rows = {key: (1, census.CLIENT, ("snapshot",), "client payload")}
    assert "private.json" in census.unclassified_site_literals(tmp_path)[key]
    assert any("'private.json'" in p for p in census.census_problems(tmp_path, rows, ["snapshot"]))


def test_cyclic_path_rebinding_keeps_other_names_without_a_budget_refusal(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py", "from pathlib import Path\n\ndef emit(path):\n"
           "    path = Path(path)\n    path = 'private.json'\n    Path(path).write_text('payload')\n")
    key = "cisco_toolkit/writer.py::emit"
    rows = {key: (1, census.CLIENT, ("snapshot",), "client payload")}
    problems = census.census_problems(tmp_path, rows, ["snapshot"])
    assert problems == [f"client write site resolves to unclassified name 'private.json': {key}"]


@pytest.mark.parametrize("assignment", [
    'a.download = `private-${id}.json`\na.click()',
    'a\n  .download\n  =\n  `private-${id}.json`\na.click()',
    'a["download"] = (`private-${id}.json`)\na.click()',
    'a.download = "private-"\n + id + ".json"\na.click()',
    'Object.assign(a, {download: `private-${id}.json`, href: blobUrl})',
    'a["down" + "load"] = `private-${id}.json`',
    'a[("down") + ("load")] = `private-${id}.json`',
    'Reflect.set(a, "down" + "load", `private-${id}.json`)',
    'saveAs(blob, `private-${id}.json`)',
    'const clean = raw.replace(/"/g, ""); a.download = `private-${id}.json`',
    r'saveAs(/\)/.test(name) ? blob : fallbackBlob, `private-${id}.json`)',
    r'downloadBlob(/[,)]/.test(name) ? blob : fallbackBlob, `private-${id}.json`)',
    r"""const prose = `${JSON.stringify(paths).replace(/'/g, "''")}`; a.download = `private-${id}.json`""",
])
def test_download_tokenizer_keeps_asi_multiline_object_and_save_exits(tmp_path, assignment):
    _write(tmp_path, "new-surface/export.mjs", assignment)
    names = census.download_names(tmp_path)
    assert names, "a direct exit disappeared"
    assert any(t == "private-0.json" for _l, _e, t in names), names
    assert all(dv.client_artifact_class("Downloads/" + t) is None for _l, _e, t in names if t)


def test_browser_source_scan_is_structural_and_generated_exits_stay_obligations(tmp_path):
    sources = {"new-root/export.js": 'a.download = "private.json"',
               "new-root/export.cjs": 'saveAs(blob, "private.json")',
               "new-root/export.html": '<a download="private.json">save</a>',
               "new-root/export.py": "HTML = " + repr('<script>a.download = "private.json"</script>'),
               "new-root/composed.py": "SCRIPT = " + repr('a.download = "private.json"')
                   + '\nHTML = f"<script>{SCRIPT}</script>"',
               "new-root/open.mjs": 'window.open(blobUrl)'}
    for path, source in sources.items():
        _write(tmp_path, path, source)
    assert set(census.download_sources(tmp_path)) == set(sources)
    names = census.download_names(tmp_path)
    assert {location.split(":")[0] for location, _e, _t in names} == set(sources)
    assert any(e == "<browser-open:blobUrl>" and t is None for _l, e, t in names)
    assert all((l.split(":")[0], e) not in census.DOWNLOAD_NAME_PASSTHROUGH for l, e, _t in names)


def test_browser_local_callbacks_and_comments_are_not_filename_assignments(tmp_path):
    _write(tmp_path, "new-root/callback.tsx", 'const download = useCallback(() => {});\n'
           '// a.download = "private.json"\n'
           'const text = "a.download = unknown";\n'
           'const View = () => <a download="flow-frames.txt">Don\'t read "prose" as JS</a>;\n'
           'const after = () => <div>{rows.map(x => <span>{x}</span>)}</div>;\n')
    assert [t for _l, _e, t in census.download_names(tmp_path)] == ["flow-frames.txt"]


def test_portable_early_positive_branch_cannot_hide_from_reconciliation():
    source = (ROOT / "portable/release_contract.py").read_text(encoding="utf-8")
    changed = source.replace("    folded = relative.casefold()", "    if relative.endswith('.private-capture'):\n"
                             "        return True\n    folded = relative.casefold()", 1)
    assert ("suffix", ".private-capture") in census.bundle_artifact_name_shapes(changed)
    function = next(n for n in ast.parse(changed).body if isinstance(n, ast.FunctionDef)
                    and n.name == "_forbidden_client_artifact")
    namespace = {"PurePosixPath": PurePosixPath}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<synthetic-owner>", "exec"), namespace)
    assert "probe.private-capture" in _bundle_owner_corpus(changed, namespace[function.name])
    assert dv.client_artifact_class("site/probe.private-capture") is None
    assert _repository_gate()._client_artifact_class("site/probe.private-capture") is None
    unsupported = changed.replace("relative.endswith('.private-capture')", "custom_selector(relative)")
    with pytest.raises(ValueError, match="unrecognised bundle"):
        census.bundle_artifact_name_shapes(unsupported)
    changed_binding = source.replace('suffix = PurePosixPath(folded).suffix',
                                    "suffix = '.db' if relative.endswith('.private-capture') "
                                    "else PurePosixPath(folded).suffix", 1)
    assert changed_binding != source
    with pytest.raises(ValueError, match="changed selector binding"):
        census.bundle_artifact_name_shapes(changed_binding)


def test_nrfu_library_export_has_a_class_and_old_spelling_does_not():
    from cisco_toolkit import nrfu_export
    tree = ast.parse((ROOT / "cisco_toolkit/nrfu_export.py").read_text(encoding="utf-8"))
    writer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "write_nrfu_pack")
    assert any(isinstance(n, ast.JoinedStr) and isinstance(n.values[-1], ast.Constant)
               and n.values[-1].value == ".nrfu.txt" for n in ast.walk(writer))
    name = f"site/wave/{nrfu_export._safe_name('CORE-1')}.nrfu.txt"
    assert dv.client_artifact_class(name) == _repository_gate()._client_artifact_class(name) == "nrfu-command-pack"
    assert dv.client_artifact_class("site/wave/CORE-1.txt") is None
    assert census.WRITE_SITE_CENSUS["cisco_toolkit/nrfu_export.py::write_nrfu_pack"][1:3] == (
        census.CLIENT, ("nrfu-command-pack",))


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
@pytest.mark.parametrize("database", ["alternate.sqlite", "alternate.sqlite3", "custom.evidence", ".backup.db.partial"])
def test_real_sqlite_companions_are_refused_on_hosted_runners(tmp_path, journal_mode, database):
    import sqlite3
    path = tmp_path / database
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"PRAGMA journal_mode = {journal_mode}")
        connection.execute("CREATE TABLE evidence (host TEXT)")
        connection.commit()
        connection.execute("INSERT INTO evidence VALUES ('CORE-1')")
        companions = [p.name for p in tmp_path.iterdir() if p != path]
        assert companions, "the transaction produced no companion witness"
        for name in companions:
            assert dv.client_artifact_class("site/" + name) == _repository_gate()._client_artifact_class("site/" + name)
            assert dv.client_artifact_class("site/" + name) in {"database-wal", "database-shm", "database-journal"}
    finally:
        connection.rollback()
        connection.close()


def test_every_database_writer_row_retains_the_complete_companion_family():
    family = {"database-wal", "database-shm", "database-journal"}
    for key, (_count, _disposition, classes, _why) in census.WRITE_SITE_CENSUS.items():
        if set(classes) & family:
            assert family <= set(classes), key


@pytest.mark.parametrize("header", ["const helper = <T,>(value: T) => value;",
                                   "const helper = <T extends object>(value: T) => value;",
                                   "const helper = <T = string>(value: T) => value;",
                                   "const helper = <T extends object = object, U = string>(v: T) => v;",
                                   'const View = () => <Component<Payload> download="private.json" />;',
                                   "const View = () => <a title={x => x > 0}>Don't parse prose</a>;"])
def test_jsx_and_typescript_syntax_does_not_hide_later_downloads(tmp_path, header):
    _write(tmp_path, "new-root/view.tsx", header + '\na.download = "private.json";\n')
    assert "private.json" in {t for _l, _e, t in census.download_names(tmp_path)}


@pytest.mark.parametrize("view", ['<a download="private.json" />',
                                 '<a download={`private-${id}.json`} />',
                                 '<Component<Payload> download="private.json" />'])
def test_self_closing_jsx_attributes_retain_their_filename(tmp_path, view):
    _write(tmp_path, "new-root/view.tsx", f"const View = () => {view};")
    names = census.download_names(tmp_path)
    assert len(names) == 1
    assert names[0][2] in {"private.json", "private-0.json"}


def test_browser_python_bindings_keep_their_lexical_scope(tmp_path):
    _write(tmp_path, "new-root/generated.py",
           "def first():\n    script = 'a.download = \\\"private.json\\\"'\n"
           "    return f'<script>{script}</script>'\n"
           "\ndef other():\n    script = 'a.download = \\\"flow-frames.txt\\\"'\n"
           "    return f'<script>{script}</script>'\n")
    names = census.download_names(tmp_path)
    assert {t for _l, _e, t in names} == {"private.json", "flow-frames.txt"}
    assert len(names) == 2


def test_duplicate_alternatives_do_not_erase_a_distinct_bad_filename():
    node = ast.Name(id="target")
    def resolver(_name):
        return [ast.Constant(value="safe.snapshot.json")] * 300 + [ast.Constant(value="private.json")]
    assert "private.json" in census._templates(node, resolver)


def test_browser_python_method_uses_module_binding_not_class_local(tmp_path):
    _write(tmp_path, "new-root/generated.py",
           "SCRIPT = 'a.download = \\\"private.json\\\"'\n"
           "class Surface:\n    SCRIPT = 'a.download = \\\"flow-frames.txt\\\"'\n"
           "    def render(self):\n        return f'<script>{SCRIPT}</script>'\n")
    assert {t for _l, _e, t in census.download_names(tmp_path)} == {"private.json"}


def test_python_regex_lookbehind_is_not_a_browser_document(tmp_path):
    _write(tmp_path, "new-root/regex.py", "def pattern(name):\n"
           "    return rf'(?<![\\w.-]){name}(?![\\w-])'\n")
    assert census.download_names(tmp_path) == []


def test_python_generated_script_string_pieces_are_assembled_before_lexing(tmp_path):
    _write(tmp_path, "new-root/generated.py", "def html(value):\n"
           + "    return f\"<script>const text='{value}'; a.download='private.json';</script>\"\n")
    assert {t for _l, _e, t in census.download_names(tmp_path)} == {"private.json"}


def test_browser_python_module_expression_keeps_its_defining_scope(tmp_path):
    _write(tmp_path, "new-root/generated.py", "NAME = 'private.json'\n"
           + "SCRIPT = f\"a.download = '{NAME}'\"\n"
           + "def html():\n    NAME = 'flow-frames.txt'\n    return f'<script>{SCRIPT}</script>'\n")
    assert {t for _l, _e, t in census.download_names(tmp_path)} == {"private.json"}


def test_browser_non_html_binding_graph_does_not_expand_paths(tmp_path):
    source = "value0 = 'plain'\n"
    source += "".join(f"value{i} = value{i-1} + value{i-1}\n" for i in range(1, 25))
    source += 'result = f"{value24}"\n'
    source += "HTML = " + repr('<script>a.download = "private.json"</script>') + "\n"
    _write(tmp_path, "new-root/generated.py", source)
    assert {t for _l, _e, t in census.download_names(tmp_path)} == {"private.json"}


def test_opaque_grouped_property_calls_do_not_recurse_or_hide_the_next_exit(tmp_path):
    _write(tmp_path, "new-root/export.mjs", 'a[(first)(second)] = value;\na.download = "private.json";')
    assert "private.json" in {t for _l, _e, t in census.download_names(tmp_path)}


def test_bogus_markup_and_regex_sections_do_not_hide_a_later_download(tmp_path):
    _write(tmp_path, "new-root/generated.py", "REGEX = " + repr('(?P<name>a)(?<![A-Za-z0-9])') + '\n')
    _write(tmp_path, "new-root/export.html", '<![A-Za-z0-9]><a download="private.json">save</a>')
    assert {t for _l, _e, t in census.download_names(tmp_path)} == {"private.json"}
