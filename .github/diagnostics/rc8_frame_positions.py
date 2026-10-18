"""Hosted content-free frame metadata observation; never locals or ownership.

One tracked-object snapshot after TARGET fixtures, before its body. Matching a
compiled public source position is not runtime code equivalence, reachability,
AST ownership, retained size, GC cost, a polluter, or timing acceptance.
"""
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import types

import pytest

SOURCE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
TREE = "aa003b01248588220d22face7e8218f96a9ada84"
TARGET = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
ROOTS = ("cisco_toolkit/", "collector/", "webapp/backend/", "webapp/tests/", "portable/", "tests/")
ROOT_FILES = ("conftest.py", "COLLECT_PARSE_V3_23_0.py")
COMPILER = sys.version
COMPILE_FLAGS = {"mode": "exec", "dont_inherit": True, "optimize": 0}
MANIFEST_LIMITS = {"max_files": 10000, "max_positions": 250000, "max_file_bytes": 4194304,
                   "max_total_source_bytes": 268435456, "max_manifest_bytes": 33554432}
LIMITS = {
    "max_objects_inspected": 3000000, "max_frame_metadata_reads": 4096, "max_matched_rows": 512,
    "snapshot_creation_uncapped": True, "snapshot_includes_pending_garbage_and_observer_references": True,
    "untracked_objects_missing": True, "source_compilation_only_in_separate_preparation_process": True,
    "sidecar_loaded_only_after_snapshot_creation": True,
    "public_compiled_position_match_not_runtime_code_equivalence": True,
    "matched_rows_omitted_counts_frame_matches_not_distinct_predicates": True,
    "no_frame_locals_back_globals_trace_referrers_or_values_read": True,
    "frame_f_code_read_emits_cpython_audit_event": True,
    "external_audit_hooks_unknown_and_not_bypassed": True,
    "audit_hooks_receive_the_frame_and_may_inspect_it": True,
    "presence_not_reachability_lifetime_ownership_size_or_timing_cause": True,
    "observer_snapshot_sidecar_source_validation_and_json_can_change_gc_phase": True,
    "observer_owned_snapshot_and_direct_frame_code_references_cleared_before_body": True,
    "gc_window_excludes_final_source_guard_and_json_emission": True,
    "no_gc_policy_order_selection_assertion_budget_timer_or_timeout_changes": True,
    "instrumented_timings_not_acceptance": True,
}
_TYPE, _LEN, _ID = type, len, id
_FRAME, _CODE, _STR, _INT = types.FrameType, types.CodeType, str, int
_PYTEST_FUNCTION = pytest.Function
_FRAME_CODE_GET = types.FrameType.f_code.__get__
_GET_OBJECTS, _GET_STATS, _GET_COUNT = gc.get_objects, gc.get_stats, gc.get_count
_RUN, _WRITE, _CLOSE, _CLOCK = subprocess.run, os.write, os.close, time.monotonic
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).encode
_STATE = {"fd": None, "root": None, "ready": False, "seen": False, "sidecar": None,
          "sidecar_sha256": None, "plugin_sha256": None}


def _git(root, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_NO_REPLACE_OBJECTS="1")
    result = _RUN(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c",
                   "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", str(root), *arguments],
                  env=environment, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("source guard refused")
    return result.stdout


def _ordinary(path, directory=False):
    metadata = path.lstat()
    if (path.is_symlink() or path.resolve(strict=True) != path
            or (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode))):
        raise ValueError("ordinary path required")
    return metadata


def _guard(root):
    git = root / ".git"
    _ordinary(root, True)
    _ordinary(git, True)
    _ordinary(git / "index")
    _ordinary(git / "objects", True)
    _ordinary(git / "config")
    if (any(os.path.lexists(path) for path in (git / "index.lock", git / "objects/info/alternates",
            git / "info/grafts", git / "info/sparse-checkout"))
            or re.search(r"(?mi)^\s*\[\s*(?:include|includeif|filter)(?:\s|\])", (git / "config").read_text())):
        raise ValueError("Git indirection refused")
    for arguments, expected in (
        (("--show-toplevel",), root), (("--absolute-git-dir",), git),
        (("--path-format=absolute", "--git-common-dir"), git),
    ):
        if Path(_git(root, "rev-parse", *arguments).decode().strip()).resolve() != expected:
            raise ValueError("source location refused")
    if (_git(root, "rev-parse", "HEAD").decode().strip() != SOURCE
            or _git(root, "rev-parse", "HEAD^{tree}").decode().strip() != TREE
            or _git(root, "status", "--porcelain", "--untracked-files=no")
            or any(row and not row.startswith(b"H ") for row in _git(root, "ls-files", "-v", "-z").split(b"\0"))):
        raise ValueError("source identity refused")
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _public(relative):
    return (type(relative) is str and 0 < len(relative) <= 1024 and "\\" not in relative
            and not relative.startswith("/") and all(part not in ("", ".", "..") for part in relative.split("/"))
            and relative.endswith(".py") and (relative in ROOT_FILES or relative.startswith(ROOTS)))


def _load_sidecar(path, expected_sha, root):
    """Admit primitives only; compile no project source in this child."""
    if type(expected_sha) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise ValueError("sidecar digest refused")
    metadata = _ordinary(path)
    if metadata.st_size > MANIFEST_LIMITS["max_manifest_bytes"]:
        raise ValueError("sidecar byte cap")
    raw = path.read_bytes()
    if len(raw) != metadata.st_size or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("sidecar bytes refused")
    manifest = json.loads(raw)
    if (type(manifest) is not dict or set(manifest) != {"format", "source", "tree", "compiler", "files", "limits",
                                                     "compile_flags", "public_roots", "root_files", "encodings"}
            or manifest["format"] != "atlas-rc8-frame-manifest/1" or manifest["source"] != SOURCE
            or manifest["tree"] != TREE or manifest["compiler"] != COMPILER
            or manifest["compile_flags"] != COMPILE_FLAGS or type(manifest["compile_flags"]["dont_inherit"]) is not bool
            or type(manifest["compile_flags"]["optimize"]) is not int
            or manifest["public_roots"] != list(ROOTS) or manifest["root_files"] != list(ROOT_FILES)
            or manifest["encodings"] != ["utf-8", "ascii"]
            or manifest["limits"] != MANIFEST_LIMITS or type(manifest["files"]) is not list
            or len(manifest["files"]) > MANIFEST_LIMITS["max_files"]):
        raise ValueError("sidecar schema refused")
    tracked = {}
    for entry in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        prefix, relative_raw = entry.split(b"\t", 1)
        relative = relative_raw.decode("utf-8")
        if _public(relative):
            mode, blob, stage = prefix.decode("ascii").split()
            if mode != "100644" or stage != "0":
                raise ValueError("public source mode refused")
            tracked[relative] = blob
    if not tracked or len(tracked) > MANIFEST_LIMITS["max_files"]:
        raise ValueError("public source scope refused")
    allowed, filenames, selected = {}, set(), set()
    total_bytes = positions = syntax_refused = 0
    for row in manifest["files"]:
        if (type(row) is not dict or set(row) != {"relative", "sha256", "status", "positions"}
                or not _public(row["relative"]) or row["relative"] in selected
                or row["relative"] not in tracked or type(row["sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
                or row["status"] not in ("compiled", "syntax_refused") or type(row["positions"]) is not list):
            raise ValueError("public row refused")
        relative = row["relative"]
        selected.add(relative)
        source = root / relative
        size = _ordinary(source).st_size
        if size > MANIFEST_LIMITS["max_file_bytes"] or total_bytes + size > MANIFEST_LIMITS["max_total_source_bytes"]:
            raise ValueError("public source byte cap")
        source_raw = source.read_bytes()
        total_bytes += len(source_raw)
        git_blob = hashlib.sha1(b"blob " + str(len(source_raw)).encode("ascii") + b"\0" + source_raw).hexdigest()
        if (len(source_raw) != size or hashlib.sha256(source_raw).hexdigest() != row["sha256"]
                or git_blob != tracked[relative]):
            raise ValueError("public source hash refused")
        filename = str(source)
        filenames.add(filename)
        if row["status"] == "syntax_refused":
            if row["positions"]:
                raise ValueError("refused source positions")
            syntax_refused += 1
        elif not row["positions"]:
            raise ValueError("compiled source positions absent")
        for position in row["positions"]:
            if (type(position) is not list or len(position) != 3
                    or type(position[0]) is not str or type(position[1]) is not str or type(position[2]) is not int
                    or not 0 < len(position[0]) <= 1024 or not 0 < len(position[1]) <= 4096
                    or not 0 <= position[2] <= 10000000):
                raise ValueError("public position refused")
            key = (filename, *position)
            if key in allowed:
                raise ValueError("duplicate public metadata predicate")
            allowed[key] = (relative, row["sha256"])
            positions += 1
            if positions > MANIFEST_LIMITS["max_positions"]:
                raise ValueError("public position cap")
    if selected != set(tracked):
        raise ValueError("public scope omitted")
    return allowed, filenames, {"files": len(selected), "positions": positions, "syntax_refused_files": syntax_refused,
                                "source_bytes": total_bytes, "sidecar_sha256": expected_sha,
                                "all_selected_public_source_bytes_verified": True,
                                "all_selected_files_compiled": syntax_refused == 0,
                                "syntax_exclusions_do_not_support_absence": True}


def _census(snapshot, allowed, approved_filenames, max_objects=3000000, max_frame_reads=4096, max_rows=512):
    inspected = min(_LEN(snapshot), max_objects)
    report = {"snapshot_total": _LEN(snapshot), "inspected": inspected,
              "uninspected_tail": _LEN(snapshot) - inspected, "frames_seen": 0, "frame_reads": 0,
              "matched_frames": 0, "unsafe_metadata": 0, "getter_refused": 0, "unknown_source": 0,
              "unapproved_position": 0, "frame_reads_omitted": 0, "matched_rows_omitted": 0}
    rows = {}
    value = code = filename = name = qualname = line = key = binding = None
    try:
        for index in range(inspected):
            value = snapshot[index]
            if _TYPE(value) is not _FRAME:
                continue
            report["frames_seen"] += 1
            if report["frame_reads"] >= max_frame_reads:
                report["frame_reads_omitted"] += 1
                continue
            report["frame_reads"] += 1
            try:
                code = _FRAME_CODE_GET(value, _FRAME)  # CPython audit event; no bypass
            except Exception:
                report["getter_refused"] += 1
                continue
            if _TYPE(code) is not _CODE:
                report["unsafe_metadata"] += 1
                continue
            filename, name, qualname, line = code.co_filename, code.co_name, code.co_qualname, code.co_firstlineno
            if (_TYPE(filename) is not _STR or _TYPE(name) is not _STR or _TYPE(qualname) is not _STR
                    or _TYPE(line) is not _INT):
                report["unsafe_metadata"] += 1
                continue
            if (not 0 < _LEN(filename) <= 8192 or not 0 < _LEN(name) <= 1024
                    or not 0 < _LEN(qualname) <= 4096 or not 0 <= line <= 10000000):
                report["unsafe_metadata"] += 1
                continue
            if filename not in approved_filenames:
                report["unknown_source"] += 1
                continue
            key = (filename, name, qualname, line)
            binding = allowed.get(key)
            if binding is None:
                report["unapproved_position"] += 1
                continue
            report["matched_frames"] += 1
            if key in rows:
                rows[key]["count"] += 1
            elif len(rows) < max_rows:
                rows[key] = {"relative": binding[0], "source_sha256": binding[1], "name": name,
                             "qualname": qualname, "firstlineno": line, "count": 1}
            else:
                report["matched_rows_omitted"] += 1
        report["matched_rows"] = sorted(rows.values(), key=lambda row: (row["relative"], row["firstlineno"], row["qualname"], row["name"]))
        report["snapshot_complete"] = report["uninspected_tail"] == 0
        report["frame_category_denominator_matches"] = report["frames_seen"] == sum(report[field] for field in (
            "matched_frames", "unsafe_metadata", "getter_refused", "unknown_source", "unapproved_position", "frame_reads_omitted"))
        report["metadata_complete_for_inspected_frames"] = not any(report[field] for field in (
            "unsafe_metadata", "getter_refused", "frame_reads_omitted", "matched_rows_omitted"))
        report["all_inspected_frames_match_approved_public_positions"] = (
            report["metadata_complete_for_inspected_frames"] and not report["unknown_source"] and not report["unapproved_position"])
        return report
    finally:
        value = code = filename = name = qualname = line = key = binding = None
        rows.clear()


def _emit(payload):
    try:
        pending = (_ENCODE(payload) + "\n").encode("utf-8")
        while pending:
            written = _WRITE(_STATE["fd"], pending)
            if written <= 0:
                raise OSError
            pending = pending[written:]
    except Exception:
        try:
            _WRITE(2, b"RC8 frame diagnostic receipt refused; read actual suite outcome.\n")
        except Exception:
            pass


def _observe():
    snapshot, allowed, filenames = None, {}, set()
    report = {"status": "observation_error", "stage": "snapshot_creation", "source": SOURCE, "tree": TREE, "limits": LIMITS,
              "plugin_sha256": _STATE["plugin_sha256"], "sidecar_sha256": _STATE["sidecar_sha256"]}
    started, before = _CLOCK(), {"stats": _GET_STATS(), "counts": _GET_COUNT()}
    try:
        snapshot = _GET_OBJECTS()  # ONE uncapped snapshot; no sidecar data was loaded before it
        report["stage"] = "observation_source_guard"
        if _guard(_STATE["root"]) != _STATE["plugin_sha256"]:
            raise ValueError("plugin changed")
        report["source_guard_at_observation"] = "pass"
        report["stage"] = "sidecar_admission"
        allowed, filenames, manifest = _load_sidecar(_STATE["sidecar"], _STATE["sidecar_sha256"], _STATE["root"])
        report["stage"] = "frame_metadata_census"
        report.update(status="observed", stage="complete", manifest=manifest, census=_census(snapshot, allowed, filenames))
    except Exception:
        pass
    finally:
        allowed.clear()
        filenames.clear()
        if snapshot is not None:
            snapshot.clear()
        snapshot = None
    report.update(gc_before=before, gc_after={"stats": _GET_STATS(), "counts": _GET_COUNT()},
                  observation_seconds=_CLOCK() - started)
    try:
        if _guard(_STATE["root"]) != _STATE["plugin_sha256"]:
            raise ValueError("plugin changed")
        report["source_guard_after"] = "pass"
    except Exception:
        report.update(status="source_guard_refused", source_guard_after="refused")
    _emit(report)


def pytest_configure(config):
    try:
        if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
                or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15) or sys.flags.optimize
                or not any(line in ('ID=ubuntu', 'ID="ubuntu"') for line in Path("/etc/os-release").read_text().splitlines())):
            raise ValueError("host refused")
        root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True) / "subject"
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        requested = Path(os.environ["ATLAS_FRAME_POSITIONS_SOURCE_ROOT"])
        output = Path(os.environ["ATLAS_FRAME_POSITIONS_REPORT"])
        sidecar = Path(os.environ["ATLAS_FRAME_POSITIONS_SIDECAR"])
        digest = os.environ["ATLAS_FRAME_POSITIONS_SIDECAR_SHA256"]
        if (requested.absolute() != root or requested.resolve(strict=True) != root
                or output.absolute() != output.resolve() or not output.is_relative_to(temporary)
                or output.is_relative_to(root) or os.path.lexists(output)
                or sidecar.absolute() != sidecar.resolve(strict=True) or not sidecar.is_relative_to(temporary)
                or sidecar.is_relative_to(root) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or os.environ.get("ATLAS_FRAME_POSITIONS_SOURCE") != SOURCE
                or os.environ.get("ATLAS_FRAME_POSITIONS_TREE") != TREE):
            raise ValueError("binding refused")
        _ordinary(sidecar)
        plugin_digest = _guard(root)
        _STATE.update(fd=os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), root=root,
                      sidecar=sidecar, sidecar_sha256=digest, plugin_sha256=plugin_digest, ready=True)
    except Exception:
        if _STATE["fd"] is not None:
            _emit({"status": "configuration_refused", "limits": LIMITS})


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_setup(item):
    outcome = yield
    if (_STATE["ready"] and not _STATE["seen"] and outcome.excinfo is None
            and _TYPE(item) is _PYTEST_FUNCTION and item.nodeid == TARGET):
        _STATE["seen"] = True
        _observe()


def pytest_unconfigure(config):
    if _STATE["fd"] is not None:
        try:
            if _STATE["ready"] and not _STATE["seen"]:
                _emit({"status": "target_not_observed", "limits": LIMITS})
        finally:
            _CLOSE(_STATE["fd"])
            _STATE.update(fd=None, ready=False, root=None, sidecar=None)
