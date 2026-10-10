"""W65: every engine write site is classified, and both privacy gates refuse every client class.

Before W65 the committed-tree gate (``.github/scripts/verify_repository_privacy.py``) and the
wheel/sdist audit (``cisco_toolkit/distribution_verify.py``) each kept a hand-written suffix list.
The engine meanwhile wrote ``.protocol-assurance.json``, ``.comparison.json``,
``.trend-comparisons.json`` and ``.phase_timings.json`` sidecars, all naming client devices, that
neither list classified. That is the "named subset instead of the structural class" defect, so the
fix is structural rather than four more list entries:

* ONE owner of client-artifact name classes, ``distribution_verify.CLIENT_ARTIFACT_NAME_CLASSES``,
  consumed by the archive audit and restated (pinned equal here) by the stdlib-only repository gate;
* a census (``tests/client_artifact_census.py``) of every write site under the engine, AssessHub
  and Atlas roots, found by AST, so a new write fails here until it is classified;
* ties from producer-owned names (docmeta, ingest markers, gate state, recall, COMMANDS_*, REST
  collectors) to the registry, and from the registry to ``.gitignore`` and the tracked tree.

Every check below is exercised with a negative control: a synthetic tree, path or literal the
check must reject.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

import client_artifact_census as census  # tests/ is on sys.path (root conftest.py)
from cisco_toolkit import distribution_verify as dv
from cisco_toolkit import docmeta, gate_state, recall
from cisco_toolkit import engine_log_path

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


def _probe(match: str, pattern: str) -> str:
    """A path a producer of this class could write, outside any reviewed fixture root."""
    if match == "suffix":
        return f"customer-output/Acme{pattern}"
    if match == "leaf":
        return f"customer-output/{pattern}"
    if match == "leaf-prefix":
        return f"customer-output/{pattern}probe.html"
    if match == "capture":
        return f"customer-output/CORE-1/{pattern}probe.txt"
    raise AssertionError(f"unknown match kind {match!r}")


def _git() -> str:
    git = shutil.which("git")
    assert git is not None, "git is required to verify the ignore and tracked-tree contracts"
    return git


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- the write-site census


def test_every_engine_write_site_is_classified():
    problems = census.census_problems(ROOT)
    assert problems == [], "\n".join(problems)


def test_every_output_name_suffix_literal_is_classified():
    problems = census.suffix_literal_problems(ROOT)
    assert problems == [], "\n".join(problems)


def test_the_census_scans_every_tracked_python_file_of_the_engine_roots():
    """Non-vacuity: the walk is the tracked source set, not an empty or partial directory list."""
    listed = subprocess.run(
        [_git(), "ls-files", "-z", "--", "COLLECT_PARSE_V3_23_0.py", "cisco_toolkit",
         "webapp/backend", "portable"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    tracked = {path for path in listed if path.endswith(".py")}
    scanned = {path.relative_to(ROOT).as_posix() for path in census.scanned_files(ROOT)}
    assert len(tracked) > 100
    assert scanned == tracked


def test_the_census_reaches_the_sidecars_both_gates_used_to_miss():
    sites = census.write_sites(ROOT)
    assert len(sites) >= 80 and sum(sites.values()) >= 120, "the census found too few write sites"
    rows = census.WRITE_SITE_CENSUS
    assert {"comparison-receipt", "trend-comparisons"} <= set(rows["COLLECT_PARSE_V3_23_0.py::main"][2])
    assert {"protocol-assurance-export", "phase-timings", "run-manifest"} <= set(
        rows["COLLECT_PARSE_V3_23_0.py::_stage_finalize"][2])
    assert rows["COLLECT_PARSE_V3_23_0.py::_write_incomplete_marker"][2] == ("incomplete-marker",)
    literals = {literal for _location, literal in census.suffix_literals(ROOT)}
    assert set(UNGUARDED_BEFORE_W65.values()) <= literals
    for key, suffix in UNGUARDED_BEFORE_W65.items():
        assert dv.client_artifact_class(f"out/Acme{suffix}") == key


def _engine_tree(tmp_path: Path, body: str) -> Path:
    _write(tmp_path, "COLLECT_PARSE_V3_23_0.py",
           "def write_json_file(path, data):\n"
           "    with open(path, 'w', encoding='utf-8') as handle:\n"
           "        handle.write(str(data))\n" + body)
    return tmp_path


_DELEGATED = {"write_json_file": "COLLECT_PARSE_V3_23_0.py"}
_BASE_ROW = {"COLLECT_PARSE_V3_23_0.py::write_json_file": (1, census.DELEGATED, (), "generic writer")}


def test_a_new_sidecar_through_a_delegated_writer_fails_the_census(tmp_path):
    root = _engine_tree(tmp_path, "\n\ndef emit(base):\n    write_json_file(base + '.new.json', {})\n")
    problems = census.census_problems(
        root, census=_BASE_ROW, registry_keys=["snapshot"], delegated=_DELEGATED)
    assert problems == ["unclassified write site: COLLECT_PARSE_V3_23_0.py::emit (1 write(s))"]
    literal_problems = census.suffix_literal_problems(root, non_client={})
    assert len(literal_problems) == 1 and "'.new.json'" in literal_problems[0]
    # Positive control: classified, the same tree is clean.
    classified = {**_BASE_ROW, "COLLECT_PARSE_V3_23_0.py::emit": (1, census.CLIENT, ("snapshot",), "x")}
    assert census.census_problems(
        root, census=classified, registry_keys=["snapshot"], delegated=_DELEGATED) == []


def test_a_passed_or_aliased_delegated_writer_is_still_a_write_site(tmp_path):
    root = _engine_tree(
        tmp_path,
        "\n\ndef emit(base, run):\n    run(write_json_file, base + '.snapshot.json', {})\n"
        "\n\ndef aliased(base):\n"
        "    from COLLECT_PARSE_V3_23_0 import write_json_file as publish\n"
        "    publish(base + '.snapshot.json', {})\n",
    )
    sites = census.scan(root, _DELEGATED)[0]
    assert sites["COLLECT_PARSE_V3_23_0.py::emit"] == 1
    assert sites["COLLECT_PARSE_V3_23_0.py::aliased"] == 1


def test_a_second_write_in_a_classified_function_and_a_vanished_row_fail_the_census(tmp_path):
    _write(tmp_path, "cisco_toolkit/writer.py",
           "from pathlib import Path\n\n\ndef emit(path):\n"
           "    Path(path).write_text('a')\n    open(path + '.log', 'a')\n")
    rows = {
        "cisco_toolkit/writer.py::emit": (1, census.CLIENT, ("engine-log",), "x"),
        "cisco_toolkit/writer.py::gone": (1, census.NON_CLIENT, (), "x"),
    }
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["engine-log"], delegated={})
    assert problems == [
        "census row has no write site any more: cisco_toolkit/writer.py::gone",
        "write count changed: cisco_toolkit/writer.py::emit census=1 observed=2",
    ]


def test_census_rows_must_name_registered_classes_and_declared_delegation(tmp_path):
    _write(tmp_path, "portable/tool.py",
           "def emit(path):\n    open(path, 'w')\n\n\ndef helper(path):\n    open(path, 'w')\n")
    rows = {
        "portable/tool.py::emit": (1, census.CLIENT, ("not-a-class",), "x"),
        "portable/tool.py::helper": (1, census.DELEGATED, (), "x"),
    }
    problems = census.census_problems(tmp_path, census=rows, registry_keys=["snapshot"], delegated={})
    assert "write site names an unregistered class 'not-a-class': portable/tool.py::emit" in problems
    assert "delegated row is not a declared DELEGATED_WRITERS definition: portable/tool.py::helper" in problems
    unclassified_reason = {"portable/tool.py::emit": (1, census.CLIENT, (), " "),
                           "portable/tool.py::helper": (1, census.NON_CLIENT, ("snapshot",), "x")}
    problems = census.census_problems(
        tmp_path, census=unclassified_reason, registry_keys=["snapshot"], delegated={})
    assert "client write site names no registry class: portable/tool.py::emit" in problems
    assert "census row gives no reason: portable/tool.py::emit" in problems
    assert "non-client write site must not name a registry class: portable/tool.py::helper" in problems


def test_a_delegated_writer_defined_twice_or_nowhere_fails_the_census(tmp_path):
    _write(tmp_path, "COLLECT_PARSE_V3_23_0.py", "def write_json_file(path):\n    pass\n")
    _write(tmp_path, "cisco_toolkit/copy.py", "def write_json_file(path):\n    pass\n")
    problems = census.census_problems(
        tmp_path, census={}, registry_keys=[], delegated={**_DELEGATED, "absent_writer": "portable/x.py"})
    assert any("'absent_writer' must be defined exactly once" in line for line in problems)
    assert any("'write_json_file' must be defined exactly once" in line for line in problems)


@pytest.mark.parametrize("source", [
    "open(p, 'w')", "open(p, 'ab')", "open(p, mode)", "open(p, mode='x')", "p.open('xb')",
    "p.open(mode='w')", "os.open(p, os.O_RDWR | os.O_CREAT)", "zipfile.ZipFile(p, 'w')",
    "tempfile.mkstemp()", "tempfile.NamedTemporaryFile(delete=False)", "sqlite3.connect(p)",
    "shutil.copy2(a, b)", "shutil.copytree(a, b)", "os.replace(a, b)", "doc.save(p)",
    "p.write_bytes(b)", "p.write_text(t)", "logging.FileHandler(p)", "gzip.open(p, 'wb')",
])
def test_write_primitives_are_recognised(source):
    assert census.write_primitive(ast.parse(source, mode="eval").body) is not None


@pytest.mark.parametrize("source", [
    "open(p)", "open(p, 'rb')", "p.open()", "p.open('rb')", "zf.open(info)",
    "opener.open(urllib.request.Request(url), timeout=5)", "zipfile.ZipFile(p)",
    "tarfile.open(p, 'r:gz')", "os.open(p, os.O_RDONLY)", "os.makedirs(d)", "Path(d).mkdir()",
    "text.replace('a', 'b')", "current.copy()",
])
def test_reads_directory_creation_and_lookalikes_are_not_write_sites(source):
    assert census.write_primitive(ast.parse(source, mode="eval").body) is None


# ---------------------------------------------------------------- one registry, two gates


def test_the_repository_gate_restates_the_owner_registry_exactly():
    gate = _repository_gate()
    assert tuple(gate._CLIENT_ARTIFACT_NAME_CLASSES) == CLASSES
    assert gate._CLIENT_ARTIFACT_EXCEPTIONS == dv.CLIENT_ARTIFACT_EXCEPTIONS
    assert gate._CLIENT_CAPTURE_FIXTURE_ROOT == dv.CLIENT_CAPTURE_FIXTURE_ROOT


def test_the_registry_is_well_formed(monkeypatch):
    keys = [key for key, _match, _pattern in CLASSES]
    assert len(keys) == len(set(keys)), "registry keys must be unique"
    assert len({pattern.casefold() for _key, _match, pattern in CLASSES}) == len(CLASSES)
    assert {match for _key, match, _pattern in CLASSES} <= set(dv.CLIENT_ARTIFACT_MATCHES)
    assert all(producer.strip() for *_row, producer in dv.CLIENT_ARTIFACT_NAME_CLASSES)
    assert dv._FORBIDDEN_SUFFIXES == tuple(p for _k, m, p in CLASSES if m == "suffix")
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
    upper = probe.upper()
    assert dv.client_artifact_class(upper) == key and gate._client_artifact_class(upper) == key


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


def test_capture_fixtures_pass_only_the_repository_gate_and_only_under_tests():
    gate = _repository_gate()
    fixture = "tests/fixtures/show_version.txt"
    assert gate._client_artifact_class(fixture) is None
    assert dv.client_artifact_class(fixture, capture_fixture_root="tests/") is None
    # Archives get no fixture exception (they also reject tests/ as a path part).
    assert dv.client_artifact_class(fixture) == "capture-show"
    for outside in ("docs/show_version.txt", "fixtures/tests/show_version.txt"):
        assert gate._client_artifact_class(outside) == "capture-show"
    assert dv._privacy_violations({"webapp/show_version.txt"}) == ["webapp/show_version.txt"]


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


def _registered_capture_filenames() -> set[str]:
    """Every capture filename the collectors write: COMMANDS_* and the REST command maps."""
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
                continue  # the computed COMMANDS_ALL union
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
    return names | rest_names


def test_every_collector_capture_filename_is_a_registered_capture_class():
    unregistered = sorted(
        name for name in _registered_capture_filenames()
        if not (dv.client_artifact_class(f"customer-output/CORE-1/{name}") or "").startswith("capture-")
    )
    assert unregistered == []


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


def test_gitignore_ignores_every_registered_class():
    probes = [_probe(match, pattern) for _key, match, pattern in CLASSES]
    missing = sorted(set(probes) - _ignored(probes))
    assert missing == [], f"client artifact classes a `git add -A` would stage: {missing}"


def test_gitignore_keeps_the_reviewed_exceptions_and_fixtures_visible():
    visible = sorted(dv.CLIENT_ARTIFACT_EXCEPTIONS) + ["tests/fixtures/show_version.txt"]
    assert _ignored(visible) == set()
    # Negative control: the probe answers "ignored" for a path this repository ignores.
    assert _ignored(["customer-output/Acme.comparison.json"]) == {"customer-output/Acme.comparison.json"}


def test_no_tracked_file_is_a_client_artifact_class():
    gate = _repository_gate()
    listed = subprocess.run([_git(), "ls-files", "-z"], cwd=ROOT, check=True,
                            capture_output=True).stdout.decode("utf-8").split("\0")
    tracked = [path for path in listed if path]
    assert len(tracked) > 1000, "the index looks wrong; this check would be vacuous"
    assert [path for path in tracked if gate._client_artifact_class(path)] == []
    # Non-vacuity: the tracked synthetic capture fixtures ARE the capture class; only the
    # reviewed tests/ root lets them through.
    fixtures = [path for path in tracked if path.startswith("tests/") and dv.client_artifact_class(path)]
    assert fixtures and all(dv.client_artifact_class(path) == "capture-show" for path in fixtures)
