"""Hosted-only, content-free heap observation; never an acceptance timing receipt.

Load as a pytest plugin with ATLAS_HEAP_REPORT and ATLAS_HEAP_SOURCE_ROOT set.
The report is JSON Lines, opened before collection outside the subject checkout.
Only --self-check executes standalone, and only inside GitHub Actions.
"""

import gc
import json
import os
import subprocess
import sys
import time
import types

import pytest

TARGET = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
MAX_OBJECTS, MAX_ROOT_VISITS, MAX_ROOT_EDGES = 1_000_000, 100_000, 200_000
MAX_STACK, MAX_POSITIONS, MAX_CELLS, TOP_CELLS = 128, 512, 20_000, 40
ROOTS = (
    ("test_ui_projection_finding_facets", "_GOLDEN", "finding_facets_golden"),
    ("test_redaction_grammar_corpus", "CORPUS", "redaction_grammar_corpus"),
    ("test_w60b_redaction", "CORPUS", "w60b_corpus"),
    ("test_w60c_redaction", "CORPUS", "w60c_corpus"),
)
LIMITS = {
    "max_objects_analyzed": MAX_OBJECTS,
    "max_root_unique_visits": MAX_ROOT_VISITS,
    "max_root_edges": MAX_ROOT_EDGES,
    "max_root_iterator_stack": MAX_STACK,
    "max_frame_positions": MAX_POSITIONS,
    "max_closure_slots": MAX_CELLS,
    "top_closure_cells": TOP_CELLS,
    "snapshot_creation_uncapped": True,
    "snapshot_can_include_pending_garbage_and_observer_objects": True,
    "untracked_objects_missing_from_snapshot": True,
    "observation_can_trigger_automatic_gc_and_change_later_timing": True,
    "shallow_bytes_are_not_exclusive_retained_bytes": True,
    "root_subtrees_deduplicated_separately_not_across_roots": True,
    "source_positions_are_filename_matches_not_ownership_proofs": True,
    "corpus_parameter_aliases_can_retain_rows_independently": True,
    "no_acceptance_timing_claim": True,
}

# Capture primitives before fixtures can patch them. No lookup hashes foreign types.
_TYPE, _ID, _LEN, _NEXT = type, id, len, next
_ITER, _RANGE, _MIN, _SORTED = iter, range, min, sorted
_DICT, _LIST, _TUPLE, _SET, _FROZENSET, _STR = dict, list, tuple, set, frozenset, str
_FUNCTION, _FRAME, _CODE, _MODULE = types.FunctionType, types.FrameType, types.CodeType, types.ModuleType
_PYTEST_FUNCTION = pytest.Function
_DICT_GET, _DICT_KEYS, _DICT_VALUES = dict.get, dict.keys, dict.values
_MODULES = sys.modules
_SENTINEL = object()
_GET_OBJECTS, _GET_STATS, _CLOCK = gc.get_objects, gc.get_stats, time.monotonic
_WRITE, _CLOSE = os.write, os.close
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":")).encode
_MODULE_DICT = types.ModuleType.__getattribute__
_SIZERS = (
    (dict, "dict", dict.__sizeof__), (list, "list", list.__sizeof__),
    (tuple, "tuple", tuple.__sizeof__), (types.FunctionType, "function", object.__sizeof__),
    (types.FrameType, "frame", types.FrameType.__sizeof__),
    (types.CellType, "cell", object.__sizeof__), (set, "set", set.__sizeof__),
    (frozenset, "frozenset", frozenset.__sizeof__), (str, "str", str.__sizeof__),
    (bytes, "bytes", bytes.__sizeof__), (bytearray, "bytearray", bytearray.__sizeof__),
    (int, "int", int.__sizeof__), (float, "float", float.__sizeof__),
    (bool, "bool", int.__sizeof__), (type(None), "none", object.__sizeof__),
    (types.CodeType, "code", types.CodeType.__sizeof__),
    (types.TracebackType, "traceback", object.__sizeof__),
    (types.ModuleType, "module", object.__sizeof__),
)
_STATE = {"fd": None, "ready": False, "seen": False, "whitelist": {}, "metadata": {}}


def _shape(value):
    kind = _TYPE(value)
    for exact, label, size in _SIZERS:
        if kind is exact:
            return label, size(value)
    return "foreign_or_unlisted", None


def _bump(counts, label, size):
    row = counts.setdefault(label, {"count": 0, "shallow_bytes": 0, "unmeasured_size_count": 0})
    row["count"] += 1
    if size is not None:
        row["shallow_bytes"] += size
    else:
        row["unmeasured_size_count"] += 1


def _walk(root, visits=MAX_ROOT_VISITS, edges=MAX_ROOT_EDGES):
    """Iterative exact-builtin traversal: no field names/content enter its result."""
    seen, stack, counts = _SET(), [_ITER((root,))], {}
    value = None
    examined, capped, foreign, measured_bytes = 0, False, 0, 0
    try:
        while stack:
            if examined >= edges:
                capped = True
                break
            value = _NEXT(stack[-1], _SENTINEL)
            if value is _SENTINEL:
                stack.pop()
                continue
            examined += 1
            identity = _ID(value)
            if identity in seen:
                continue
            if _LEN(seen) >= visits:
                capped = True
                break
            seen.add(identity)
            label, size = _shape(value)
            _bump(counts, label, size)
            if size is not None:
                measured_bytes += size
            kind = _TYPE(value)
            if label == "foreign_or_unlisted":
                foreign += 1
            if kind is _DICT:
                if _LEN(stack) + 2 > MAX_STACK:
                    capped = True
                    continue
                stack.append(_ITER(_DICT_KEYS(value)))
                stack.append(_ITER(_DICT_VALUES(value)))
            elif kind is _LIST or kind is _TUPLE or kind is _SET or kind is _FROZENSET:
                if _LEN(stack) >= MAX_STACK:
                    capped = True
                    continue
                stack.append(_ITER(value))  # exact builtin identity checked above
        return {"status": "observed", "unique_visits": _LEN(seen), "edges_examined": examined,
                "traversal_capped": capped, "foreign_or_unlisted": foreign,
                "measured_builtin_shallow_bytes": measured_bytes, "types": counts}
    finally:
        value = None
        stack.clear()
        seen.clear()


def _position(code, whitelist):
    if _TYPE(code) is not _CODE or _TYPE(code.co_filename) is not _STR:
        return None
    relative = _DICT_GET(whitelist, code.co_filename)
    return None if relative is None else (relative, code.co_firstlineno)


def _summarize(snapshot, whitelist):
    counts, frames, cells = {}, {}, []
    frame_unknown, frame_overflow, function_unknown, cell_slots = 0, 0, 0, 0
    cell_slots_capped = False
    obj = closure = cell = content = None
    try:
        for index in _RANGE(_MIN(_LEN(snapshot), MAX_OBJECTS)):
            obj = snapshot[index]
            label, size = _shape(obj)
            _bump(counts, label, size)
            if _TYPE(obj) is _FRAME:
                position = _position(obj.f_code, whitelist)
                if position is None:
                    frame_unknown += 1
                elif position in frames or _LEN(frames) < MAX_POSITIONS:
                    frames[position] = frames.get(position, 0) + 1
                else:
                    frame_overflow += 1
            elif _TYPE(obj) is _FUNCTION:
                position = _position(obj.__code__, whitelist)
                if position is None:
                    function_unknown += 1
                    continue
                closure = obj.__closure__
                if closure is None:
                    continue
                for cell_index in _RANGE(_LEN(closure)):
                    if cell_slots >= MAX_CELLS:
                        cell_slots_capped = True
                        break
                    cell_slots += 1
                    cell = closure[cell_index]
                    try:
                        content = cell.cell_contents
                    except ValueError:  # exact CPython empty cell
                        continue
                    cell_label, cell_size = _shape(content)
                    record = {"source": position[0], "first_line": position[1],
                              "cell_index": cell_index, "type": cell_label,
                              "shallow_bytes": cell_size}
                    cells.append(record)
                    cells.sort(key=_cell_order, reverse=True)
                    del cells[TOP_CELLS:]
        return {"snapshot_count": _LEN(snapshot), "examined": _MIN(_LEN(snapshot), MAX_OBJECTS),
                "analysis_capped": _LEN(snapshot) > MAX_OBJECTS, "types": counts,
                "frames": [{"source": p[0], "first_line": p[1], "count": count}
                           for p, count in _SORTED(frames.items())],
                "frames_unknown_source": frame_unknown, "frame_positions_overflow": frame_overflow,
                "functions_unknown_source": function_unknown,
                "closure_slots_examined": cell_slots, "closure_slots_capped": cell_slots_capped,
                "largest_observed_closure_cells": cells}
    finally:
        obj = closure = cell = content = None


def _cell_order(row):
    return row["shallow_bytes"] if row["shallow_bytes"] is not None else -1


def _roots(modules):
    reports = {}
    module = namespace = root = None
    try:
        for module_name, binding, label in ROOTS:
            module = _DICT_GET(modules, module_name)
            if module is None:
                reports[label] = {"status": "absent_module"}
                continue
            if _TYPE(module) is not _MODULE:
                reports[label] = {"status": "foreign_module"}
                continue
            namespace = _MODULE_DICT(module, "__dict__")
            if binding not in namespace:
                reports[label] = {"status": "absent_binding"}
                continue
            root = _DICT_GET(namespace, binding)
            if _TYPE(root) is not _DICT and _TYPE(root) is not _LIST:
                reports[label] = {"status": "unexpected_root_type", "type": _shape(root)[0]}
                continue
            try:
                reports[label] = _walk(root)
            except Exception:
                reports[label] = {"status": "traversal_error"}
        return reports
    finally:
        module = namespace = root = None


def _emit(payload):
    """Only probe-generated primitive records reach this preopened descriptor."""
    try:
        pending = (_ENCODE(payload) + "\n").encode("utf-8")
        while pending:
            written = _WRITE(_STATE["fd"], pending)
            if written <= 0:
                raise OSError
            pending = pending[written:]
    except Exception:
        try:
            _WRITE(2, b"RC8 heap diagnostic report failed; product outcome unchanged.\n")
        except Exception:
            pass


def _observe():
    snapshot = None
    report = {"status": "observation_error", "limits": LIMITS, **_STATE["metadata"]}
    started = _CLOCK()
    before = _GET_STATS()
    try:
        snapshot = _GET_OBJECTS()  # one uncapped snapshot creation, explicitly disclosed
        report = {"status": "observed", "limits": LIMITS, **_STATE["metadata"],
                  "heap": _summarize(snapshot, _STATE["whitelist"]), "roots": _roots(_MODULES)}
    except Exception:
        pass  # diagnostics never replace the original test result
    finally:
        if snapshot is not None:
            snapshot.clear()  # also breaks any snapshot -> observer-frame -> snapshot cycle
        snapshot = None
    report["gc_stats_before"] = before
    report["gc_stats_after"] = _GET_STATS()
    report["observation_seconds"] = _CLOCK() - started
    _emit(report)


def pytest_configure(config):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        root = os.path.realpath(os.environ["ATLAS_HEAP_SOURCE_ROOT"])
        output = os.path.realpath(os.environ["ATLAS_HEAP_REPORT"])
        if os.path.commonpath((root, output)) == root:
            raise ValueError("report must be outside source")
        _STATE["fd"] = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        tracked = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=root,
                                 capture_output=True, check=True, timeout=60).stdout
        whitelist = {}
        for relative in tracked.decode("utf-8").split("\0"):
            if relative and not relative.startswith("/") and ".." not in relative.split("/"):
                whitelist[os.path.join(root, relative)] = relative
                whitelist[relative] = relative
        _STATE["whitelist"] = whitelist
        _STATE["metadata"] = {"source": _hex_metadata("ATLAS_HEAP_SOURCE"),
                              "tree": _hex_metadata("ATLAS_HEAP_TREE"),
                              "tracked_python_files": _LEN(whitelist) // 2}
        _STATE["ready"] = True
    except Exception:
        if _STATE["fd"] is not None:
            _emit({"status": "configuration_error"})


def _hex_metadata(name):
    value = os.environ.get(name)
    return value if value is not None and _LEN(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    ) else None


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_setup(item):
    outcome = yield
    if (_STATE["ready"] and not _STATE["seen"] and outcome.excinfo is None
            and _TYPE(item) is _PYTEST_FUNCTION and item.nodeid == TARGET):
        _STATE["seen"] = True
        try:
            _observe()
        except Exception:
            _emit({"status": "observation_error"})


def pytest_unconfigure(config):
    if _STATE["fd"] is not None:
        try:
            if not _STATE["seen"]:
                _emit({"status": "target_not_observed", "limits": LIMITS})
        finally:
            try:
                _CLOSE(_STATE["fd"])
            except OSError:
                pass
            _STATE["fd"] = None
            _STATE["whitelist"].clear()


def _self_check():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("heap self-check is GitHub Actions only")

    class ForeignMeta(type):
        def __hash__(cls):
            raise AssertionError("foreign metaclass hash called")

    class Foreign(metaclass=ForeignMeta):
        def __getattribute__(self, name):
            raise AssertionError("foreign attribute called")

        def __sizeof__(self):
            raise AssertionError("foreign sizeof called")

        def __repr__(self):
            raise AssertionError("foreign repr called")

        def __iter__(self):
            raise AssertionError("foreign iterator called")

    cycle = []
    cycle.append(cycle)
    observed = _walk(cycle)
    assert observed["unique_visits"] == 1 and not observed["traversal_capped"]
    shared = []
    assert _walk([shared, shared])["types"]["list"]["count"] == 2
    assert _walk(list(range(100)), visits=3)["traversal_capped"]
    assert _walk(cycle, edges=1)["traversal_capped"]
    assert _walk([Foreign()])["foreign_or_unlisted"] == 1
    canary = "RC8-PRIVATE-CONTENT-MUST-NEVER-BE-EMITTED"
    payload = [canary]

    def closure():
        return payload

    summary = _summarize([closure, Foreign()], {closure.__code__.co_filename: "tests/synthetic.py"})
    assert summary["largest_observed_closure_cells"][0]["type"] == "list"
    module = types.ModuleType("synthetic")
    module.CORPUS = {canary: [canary, Foreign()]}
    roots = _roots({"test_redaction_grammar_corpus": module})
    encoded = _ENCODE({"summary": summary, "roots": roots})
    assert canary not in encoded and "Foreign" not in encoded and "synthetic.py" in encoded
    assert roots["finding_facets_golden"]["status"] == "absent_module"
    cycle.clear()
    print('{"self_check":"passed"}')


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-check"]:
        raise SystemExit("only --self-check is supported")
    _self_check()
