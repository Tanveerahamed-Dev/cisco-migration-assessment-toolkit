"""Hosted-only synthetic frame/sidecar checks; never a target timing receipt.

No project code is imported or executed. The isolated audit child installs its
own refusing hook, then exits; no audit hook is bypassed or added to pytest.
"""

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import weakref

SOURCE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
TREE = "aa003b01248588220d22face7e8218f96a9ada84"
CANARIES = ("RC8_PRIVATE_FRAME_VALUE", "RC8_PRIVATE_FRAME_FILENAME", "RC8_PRIVATE_UNAPPROVED_QUALNAME")
_TYPE = type
_STAGE = {"stage": "arguments", "check": "none"}
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).encode
_EXCEPTIONS = ((AssertionError, "AssertionError"), (TypeError, "TypeError"), (ValueError, "ValueError"),
               (KeyError, "KeyError"), (AttributeError, "AttributeError"), (ImportError, "ImportError"),
               (ModuleNotFoundError, "ModuleNotFoundError"), (SyntaxError, "SyntaxError"),
               (OSError, "OSError"), (FileNotFoundError, "FileNotFoundError"), (PermissionError, "PermissionError"),
               (RuntimeError, "RuntimeError"), (MemoryError, "MemoryError"), (RecursionError, "RecursionError"),
               (SystemError, "SystemError"), (subprocess.TimeoutExpired, "TimeoutExpired"))


def _at(stage, check="none"):
    _STAGE.update(stage=stage, check=check)  # literal labels or the literal metadata-field loop only


def _category(error):
    kind = _TYPE(error)
    for exact, label in _EXCEPTIONS:
        if kind is exact:
            return label
    return "unlisted"


class _Canary:
    def __getattribute__(self, name):
        raise AssertionError("canary attribute read")

    def __repr__(self):
        raise AssertionError("canary repr")

    def __str__(self):
        raise AssertionError("canary str")

    def __sizeof__(self):
        raise AssertionError("canary size")


def _make_frame():
    canary = _Canary()
    canary.payload = "RC8_PRIVATE_FRAME_VALUE"
    return sys._getframe(), weakref.ref(canary)


def _different_frame():
    canary = _Canary()
    canary.payload = "RC8_PRIVATE_FRAME_VALUE"
    deliberate_extra_local = 17
    if deliberate_extra_local:
        return sys._getframe(), weakref.ref(canary)
    raise AssertionError("unreachable synthetic branch")


def _predicate(code):
    assert _TYPE(code) is types.CodeType
    values = code.co_filename, code.co_name, code.co_qualname, code.co_firstlineno
    assert all(_TYPE(value) is str for value in values[:3]) and _TYPE(values[3]) is int
    return values


def _allowed(code):
    key = _predicate(code)
    return {key: ("tests/synthetic_frame_owner.py", "0" * 64)}, {key[0]}


def _denominator(report):
    fields = ("matched_frames", "unknown_source", "unapproved_position", "unsafe_metadata", "getter_refused",
              "frame_reads_omitted")
    assert all(_TYPE(report[field]) is int and report[field] >= 0 for field in fields)
    assert report["frames_seen"] == sum(report[field] for field in fields)


def _private_absent(report, private_filename=None):
    encoded = _ENCODE(report)
    assert all(canary not in encoded for canary in CANARIES)
    if private_filename is not None:
        assert private_filename not in encoded
    assert "Poison" not in encoded


def _synthetic(plugin):
    class PoisonMeta(type):
        def __hash__(cls):
            raise AssertionError("foreign metaclass hash")

        def __eq__(cls, other):
            raise AssertionError("foreign metaclass equality")

    class Poison(metaclass=PoisonMeta):
        def __getattribute__(self, name):
            raise AssertionError("foreign attribute")

        def __repr__(self):
            raise AssertionError("foreign repr")

        def __sizeof__(self):
            raise AssertionError("foreign size")

        def __iter__(self):
            raise AssertionError("foreign iteration")

    _at("positive_frame")
    frame, reference = _make_frame()
    code = frame.f_code
    allowed, filenames = _allowed(code)
    snapshot = [None] * 1_000_001 + [Poison(), frame]
    try:
        _at("positive_tail_census")
        complete = plugin._census(snapshot, allowed, filenames)
        _denominator(complete)
        assert complete["snapshot_total"] == complete["inspected"] == len(snapshot)
        assert complete["uninspected_tail"] == 0 and complete["frames_seen"] == complete["frame_reads"] == 1
        assert complete["matched_frames"] == 1 and complete["metadata_complete_for_inspected_frames"]
        assert complete["matched_rows"] == [{"relative": "tests/synthetic_frame_owner.py", "source_sha256": "0" * 64,
                                            "name": code.co_name, "qualname": code.co_qualname,
                                            "firstlineno": code.co_firstlineno, "count": 1}]
        _private_absent(complete, code.co_filename)
        _at("truncated_snapshot")
        prefix = plugin._census(snapshot, allowed, filenames, max_objects=1_000_000)
        _denominator(prefix)
        assert prefix["uninspected_tail"] == len(snapshot) - 1_000_000 and prefix["frames_seen"] == 0
        _at("read_cap")
        read_cap = plugin._census([frame], allowed, filenames, max_frame_reads=0)
        _denominator(read_cap)
        assert read_cap["frame_reads"] == 0 and read_cap["frame_reads_omitted"] == 1
        assert not read_cap["metadata_complete_for_inspected_frames"]
        _at("row_cap")
        row_cap = plugin._census([frame], allowed, filenames, max_rows=0)
        _denominator(row_cap)
        assert row_cap["matched_frames"] == row_cap["matched_rows_omitted"] == 1
        assert not row_cap["metadata_complete_for_inspected_frames"]
        _at("synthetic_private_absence")
        _private_absent({"prefix": prefix, "read_cap": read_cap, "row_cap": row_cap}, code.co_filename)
    finally:
        snapshot.clear()
        allowed.clear()
        filenames.clear()
        frame = code = None
    _at("snapshot_reference_cleanup")
    assert reference() is None  # no manual GC; no returned local frame variable/self-cycle
    return {"beyond_old_1m_boundary_found": True, "tail_and_read_row_caps_explicit": True,
            "foreign_poison_hooks_not_called": True, "snapshot_aliases_released_canary_dead": True}


def _metadata_case(plugin, field, poison_type):
    code = _make_frame.__code__
    allowed, filenames = _allowed(code)
    _at("metadata_constructor", field)
    try:
        changed = code.replace(**{field: poison_type("RC8_PRIVATE_UNAPPROVED_QUALNAME")})
    except (TypeError, ValueError):
        return "constructor_refused"
    actual = getattr(changed, field)  # literal field on exact CodeType
    retained = _TYPE(actual) is poison_type
    _at("metadata_frame", field)
    factory = types.FunctionType(changed, globals())
    frame, reference = factory()
    try:
        _at("metadata_census", field)
        report = plugin._census([frame], allowed, filenames)
        _denominator(report)
        if retained:
            assert report["unsafe_metadata"] == 1 and not report["metadata_complete_for_inspected_frames"]
        else:
            assert report["unsafe_metadata"] == 0 and report["matched_frames"] == 0
            assert report["unknown_source"] + report["unapproved_position"] == 1
        assert not report["matched_rows"]
        _private_absent(report, code.co_filename)
    finally:
        frame = factory = changed = code = actual = None
        allowed.clear()
        filenames.clear()
    _at("metadata_reference_cleanup", field)
    assert reference() is None
    return "preserved_and_refused" if retained else "normalized_and_unapproved"


def _metadata(plugin):
    class PoisonStr(str):
        def __eq__(self, other):
            raise AssertionError("foreign metadata equality")

        def __hash__(self):
            raise AssertionError("foreign metadata hash")

        def __str__(self):
            raise AssertionError("foreign metadata str")

        def __repr__(self):
            raise AssertionError("foreign metadata repr")

    branches = {field: _metadata_case(plugin, field, PoisonStr)
                for field in ("co_filename", "co_name", "co_qualname")}
    original = _make_frame.__code__
    allowed, filenames = _allowed(original)
    _at("healthy_constructor")
    healthy = original.replace(co_filename=original.co_filename, co_name=original.co_name,
                               co_qualname=original.co_qualname)
    assert _predicate(healthy) == _predicate(original) and healthy.co_code == original.co_code
    factory = types.FunctionType(healthy, globals())
    frame, reference = factory()
    try:
        report = plugin._census([frame], allowed, filenames)
        _denominator(report)
        assert report["matched_frames"] == 1 and report["metadata_complete_for_inspected_frames"]
        _private_absent(report, original.co_filename)
    finally:
        frame = factory = healthy = None
    assert reference() is None
    _at("exact_approved_metadata_spoof")
    other = _different_frame.__code__
    assert other.co_code != original.co_code
    spoof = other.replace(co_filename=original.co_filename, co_name=original.co_name,
                          co_qualname=original.co_qualname, co_firstlineno=original.co_firstlineno)
    factory = types.FunctionType(spoof, globals())
    frame, reference = factory()
    try:
        report = plugin._census([frame], allowed, filenames)
        _denominator(report)
        assert report["matched_frames"] == 1  # deliberate predicate match, NOT authenticated runtime code
        _private_absent(report, original.co_filename)
    finally:
        frame = factory = spoof = other = original = None
        allowed.clear()
        filenames.clear()
    assert reference() is None
    return {"subclass_branches": branches, "healthy_exact_metadata_matched": True,
            "different_bytecode_with_approved_metadata_also_matched": True}


def _unknown(plugin):
    code = _make_frame.__code__
    allowed, filenames = _allowed(code)
    results = {}
    for field, value, expected in (("co_filename", "RC8_PRIVATE_FRAME_FILENAME", "unknown_source"),
                                   ("co_qualname", "RC8_PRIVATE_UNAPPROVED_QUALNAME", "unapproved_position")):
        _at("unknown_metadata", field)
        changed = code.replace(**{field: value})
        factory = types.FunctionType(changed, globals())
        frame, reference = factory()
        try:
            report = plugin._census([frame], allowed, filenames)
            _denominator(report)
            assert report[expected] == 1 and report["matched_frames"] == 0 and not report["matched_rows"]
            _private_absent(report, code.co_filename)
        finally:
            frame = factory = changed = None
        assert reference() is None
        results[field] = expected
    allowed.clear()
    filenames.clear()
    return results


def _audit_child(plugin):
    class AuditRefusal(RuntimeError):
        pass

    _at("audit_frame_before_hook")
    frame, reference = _make_frame()
    code = frame.f_code
    allowed, filenames = _allowed(code)
    events = [0]

    def refuse(event, arguments):
        if event == "object.__getattr__" and len(arguments) == 2 and arguments[1] == "f_code":
            events[0] += 1
            raise AuditRefusal("declared synthetic refusal")

    sys.addaudithook(refuse)  # permanent only in this separate isolated process
    _at("audit_census")
    try:
        report = plugin._census([frame], allowed, filenames)
        _denominator(report)
        assert events == [1] and report["getter_refused"] == 1
        assert report["matched_frames"] == 0 and not report["metadata_complete_for_inspected_frames"]
        assert not report["matched_rows"]
        _private_absent(report, code.co_filename)
    finally:
        frame = code = None
        allowed.clear()
        filenames.clear()
    assert reference() is None
    return {"audit_child": "passed", "audit_events": 1, "getter_refused": 1}


def _ordinary(path, directory=False):
    metadata = path.lstat()
    if (path.resolve(strict=True) != path or stat.S_ISLNK(metadata.st_mode)
            or (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode))):
        raise ValueError("ordinary path required")
    if not directory and metadata.st_nlink != 1:
        raise ValueError("single file link required")
    return metadata


def _host(arguments):
    _at("host_guard")
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15) or sys.flags.optimize
            or sys.implementation.name != "cpython"
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host refused")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
               for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
        raise ValueError("Ubuntu required")
    plugin_path = Path(__file__).resolve(strict=True).with_name("rc8_frame_positions.py")
    if arguments.plugin.absolute() != plugin_path or arguments.plugin.resolve(strict=True) != plugin_path:
        raise ValueError("plugin refused")
    _ordinary(plugin_path)
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    _ordinary(temporary, True)
    if arguments.audit_child:
        if any(value is not None for value in (arguments.output, arguments.subject, arguments.sidecar, arguments.sidecar_sha256)):
            raise ValueError("internal arguments refused")
        return plugin_path, temporary, None, None
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = workspace / "subject"
    if arguments.subject is None or arguments.subject.absolute() != root or arguments.subject.resolve(strict=True) != root:
        raise ValueError("subject refused")
    _ordinary(root, True)
    output, sidecar = arguments.output, arguments.sidecar
    if (output is None or sidecar is None or output.absolute() != output.resolve()
            or not output.is_relative_to(temporary) or output.is_relative_to(workspace) or os.path.lexists(output)
            or sidecar.absolute() != sidecar.resolve(strict=True) or not sidecar.is_relative_to(temporary)
            or sidecar.is_relative_to(workspace)):
        raise ValueError("external output or sidecar refused")
    _ordinary(output.parent, True)
    _ordinary(sidecar)
    return plugin_path, temporary, output, root


@contextmanager
def _capture(temporary, record):
    streams = sys.stdout, sys.stderr
    for stream in streams:
        stream.flush()
    with tempfile.TemporaryFile(dir=temporary) as stdout, tempfile.TemporaryFile(dir=temporary) as stderr:
        saved = os.dup(1), os.dup(2)
        try:
            os.dup2(stdout.fileno(), 1)
            os.dup2(stderr.fileno(), 2)
            yield
        finally:
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                except Exception:
                    record["flush_refused"] = True
            sys.stdout, sys.stderr = streams
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
            record.update(stdout_bytes=os.fstat(stdout.fileno()).st_size,
                          stderr_bytes=os.fstat(stderr.fileno()).st_size)


def _import(plugin_path):
    _at("plugin_import")
    spec = importlib.util.spec_from_file_location("_rc8_frame_selfcheck_plugin", plugin_path)
    if spec is None or spec.loader is None:
        raise ValueError("source loader refused")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _actual_sidecar(plugin, root, path, digest):
    _at("actual_source_guard")
    # This validates the actual fixed subject, including its tracked clean state.
    guarded_plugin = plugin._guard(root)
    assert _TYPE(guarded_plugin) is str and len(guarded_plugin) == 64
    assert all(character in "0123456789abcdef" for character in guarded_plugin)
    _at("actual_sidecar_admission")
    allowed, filenames, summary = plugin._load_sidecar(path, digest, root)
    try:
        assert summary["all_selected_public_source_bytes_verified"] is True
        assert _TYPE(summary["files"]) is int and summary["files"] == len(filenames) > 0
        assert _TYPE(summary["positions"]) is int and summary["positions"] == len(allowed) > 0
        assert _TYPE(summary["syntax_refused_files"]) is int and 0 <= summary["syntax_refused_files"] <= summary["files"]
        assert summary["all_selected_files_compiled"] is (summary["syntax_refused_files"] == 0)
        assert summary["sidecar_sha256"] == digest
        approved = {field: summary[field] for field in (
            "files", "positions", "syntax_refused_files", "source_bytes", "sidecar_sha256",
            "all_selected_public_source_bytes_verified", "all_selected_files_compiled",
            "syntax_exclusions_do_not_support_absence")}
    finally:
        allowed.clear()
        filenames.clear()
    _at("actual_sidecar_wrong_hash")
    wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
    refused = False
    try:
        plugin._load_sidecar(path, wrong, root)
    except ValueError:
        refused = True
    assert refused
    approved["wrong_hash_refused"] = True
    _at("actual_source_guard_after")
    assert plugin._guard(root) == guarded_plugin
    return approved


def _write(path, report):
    pending = (_ENCODE(report) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("receipt type refused")
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise OSError("receipt refused")
            pending = pending[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    for name in ("subject", "sidecar", "output"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--sidecar-sha256")
    parser.add_argument("--audit-child", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    report = {"status": "refused", "stage": "host_guard", "check": "none",
              "limits": {"synthetic_frame_predicates_not_target_observation": True,
                         "no_locals_back_referrers_globals_or_private_values_read_by_observer": True,
                         "external_audit_hooks_can_observe_frame_arguments": True,
                         "no_gc_collection_or_policy_change": True,
                         "metadata_match_not_runtime_code_equivalence": True}}
    output = None
    try:
        plugin_path, temporary, output, root = _host(arguments)
        report.update(plugin_sha256=hashlib.sha256(plugin_path.read_bytes()).hexdigest(),
                      selfcheck_sha256=hashlib.sha256(Path(__file__).resolve(strict=True).read_bytes()).hexdigest())
        report["captured_output"] = {}
        with _capture(temporary, report["captured_output"]):
            plugin = _import(plugin_path)
            if arguments.audit_child:
                audit = _audit_child(plugin)
            else:
                report["actual_manifest"] = _actual_sidecar(plugin, root, arguments.sidecar, arguments.sidecar_sha256)
                report["synthetic"] = _synthetic(plugin)
                report["unknown_positions"] = _unknown(plugin)
                report["metadata"] = _metadata(plugin)
                _at("isolated_audit_child")
                child = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve(strict=True)),
                                        "--plugin", str(plugin_path), "--audit-child"], capture_output=True,
                                       timeout=60, check=False)
                report["audit_child_process"] = {"exit_code": child.returncode, "stdout_bytes": len(child.stdout),
                                                 "stderr_bytes": len(child.stderr)}
                if child.returncode != 0 and len(child.stdout) <= 4096:
                    # Never copy arbitrary child output. Only these fixed internal
                    # labels/categories can augment a refused parent receipt.
                    try:
                        failed = json.loads(child.stdout)
                        if (type(failed) is dict and set(failed) <= {"status", "stage", "check", "exception_category"}
                                and failed.get("status") == "refused"
                                and failed.get("stage") in ("host_guard", "plugin_import", "audit_frame_before_hook", "audit_census")
                                and failed.get("check") == "none"
                                and failed.get("exception_category") in [label for _kind, label in _EXCEPTIONS] + ["unlisted"]):
                            report["audit_child_refusal"] = failed
                    except (ValueError, TypeError):
                        pass
                assert child.returncode == 0
                assert len(child.stdout) <= 4096
                audit = json.loads(child.stdout)
                assert audit == {"audit_child": "passed", "audit_events": 1, "getter_refused": 1}
                report["audit_child"] = {**audit, "stderr_bytes": len(child.stderr)}
        if arguments.audit_child:
            print(_ENCODE(audit))
            return 0
        report.update(status="passed", stage="complete", check="none")
        exit_code = 0
    except Exception as error:
        report.update(_STAGE)
        report["exception_category"] = _category(error)
        exit_code = 1
    if output is None:
        print(_ENCODE({key: report[key] for key in ("status", "stage", "check", "exception_category") if key in report}))
        return exit_code
    try:
        _write(output, report)
    except Exception:
        print('{"status":"receipt_write_refused"}')
        return 1
    print(_ENCODE({"self_check": report["status"], "receipt_written": True}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
