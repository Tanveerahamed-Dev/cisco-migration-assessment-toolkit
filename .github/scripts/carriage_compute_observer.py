"""Opt-in, reporting-only observer for the unchanged G14 compute budget.

Loaded only by the paired hosted investigation through PYTEST_PLUGINS. The
original _timed implementation still measures the original callable exactly once,
including this observer's small boundary/callback overhead. No collection,
threshold, cache, timer, assertion, selection or test-order policy is changed.
The allocating object census waits until BOTH original budget tests finish.
It counts GC-tracked objects, including unreachable cycles awaiting natural GC;
these are post-target retained-state observations, not proof of live ownership.
Recent natural generation-2 events are also retained, so a pause just before the
original timer is visible. This reduces, but cannot eliminate, observer effects.
"""
from array import array
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import types

import pytest


_COMPUTE = "tests/test_vlan_carriage_budget.py::test_the_stored_section_and_its_summary_stay_within_their_size_and_latency_budgets"
_API = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
_CAPACITY = 2048
# Numeric buffers avoid one newly GC-tracked tuple/dict per collector callback.
_EVENTS = array("d", [0.0]) * (_CAPACITY * 8)
_START_WALL = array("d", [0.0]) * 3
_START_CPU = array("d", [0.0]) * 3
_START_COMPUTE_PHASE = array("b", [0]) * 3
_TOTAL_WALL = array("d", [0.0]) * 3
_TOTAL_CPU = array("d", [0.0]) * 3
_COUNTS = array("q", [0]) * 3
_MAJOR_CAPACITY = 32
_MAJORS = array("d", [0.0]) * (_MAJOR_CAPACITY * 7)
_MAJOR_NODES = [None] * _MAJOR_CAPACITY
_MAJOR_PHASES = [None] * _MAJOR_CAPACITY
_event_count = 0
_major_count = 0
_major_frozen = False
_major_node = None
_major_phase = None
_callback_errors = 0
_node_id = None
_phase = "session"
_compute_phase = 0  # 0 outside, 1 observer-before, 2 original callable, 3 observer-after
_origin = 0.0
_measurement = dict.fromkeys((
    "gc_count_before", "gc_count_after", "gc_enabled_before", "gc_enabled_after",
    "gc_threshold_before", "gc_threshold_after", "threads_before", "threads_after",
    "caches_before", "caches_after", "wall_ms", "process_cpu_ms", "original_timer_ms",
    "callable_wall_ms", "callable_process_cpu_ms", "observer_error",
))
_measurement_ready = False
_published = False
_source_paths = {"budget": None, "compute": None}
_active_call = None
_original_timed = None
_budget_module = None
_vlan_module = None
_armed = False
_enabled = "G14_OBSERVER_PARENT_PID" not in os.environ
if _enabled:
    os.environ["G14_OBSERVER_PARENT_PID"] = str(os.getpid())


def _gc_event(phase, info):
    global _callback_errors
    try:
        _record_gc_event(phase, info)
    except Exception:
        _callback_errors += 1  # Incomplete telemetry, never a replacement for the original call.


def _record_gc_event(phase, info):
    global _event_count, _major_count, _major_node, _major_phase
    if _major_frozen:
        return
    generation = info["generation"]
    if not _compute_phase and generation != 2:
        return
    wall, cpu = time.perf_counter(), time.process_time()
    if phase == "start":
        _START_WALL[generation], _START_CPU[generation] = wall, cpu
        _START_COMPUTE_PHASE[generation] = _compute_phase
        if generation == 2:
            _major_node, _major_phase = _node_id, _phase
        return
    elapsed, cpu_elapsed = wall - _START_WALL[generation], cpu - _START_CPU[generation]
    if _START_COMPUTE_PHASE[generation]:
        _TOTAL_WALL[generation] += elapsed
        _TOTAL_CPU[generation] += cpu_elapsed
        _COUNTS[generation] += 1
        if _event_count < _CAPACITY:
            offset = _event_count * 8
            _EVENTS[offset] = generation
            _EVENTS[offset + 1] = 1000 * (_START_WALL[generation] - _origin)
            _EVENTS[offset + 2] = 1000 * elapsed
            _EVENTS[offset + 3] = 1000 * cpu_elapsed
            _EVENTS[offset + 4] = info["collected"]
            _EVENTS[offset + 5] = info["uncollectable"]
            _EVENTS[offset + 6] = 1000 * (wall - _origin)
            _EVENTS[offset + 7] = _START_COMPUTE_PHASE[generation]
        _event_count += 1
    if generation == 2:
        slot = _major_count % _MAJOR_CAPACITY
        offset = slot * 7
        _MAJORS[offset] = _START_WALL[generation]
        _MAJORS[offset + 1] = wall
        _MAJORS[offset + 2] = 1000 * elapsed
        _MAJORS[offset + 3] = 1000 * cpu_elapsed
        _MAJORS[offset + 4] = info["collected"]
        _MAJORS[offset + 5] = info["uncollectable"]
        _MAJORS[offset + 6] = _START_COMPUTE_PHASE[generation]
        _MAJOR_NODES[slot], _MAJOR_PHASES[slot] = _major_node, _major_phase
        _major_count += 1


def pytest_sessionstart(session):
    if _enabled:
        gc.callbacks.append(_gc_event)


def pytest_collection_finish(session):
    """Preserve the real ordered denominator, never sort or reselect it."""
    if not _enabled:
        return
    directory = Path(os.environ["G14_OBSERVER_OUTPUT"])
    directory.mkdir(parents=True, exist_ok=True)
    ordered = [item.nodeid for item in session.items]
    (directory / "collection.json").write_text(json.dumps(ordered), encoding="utf-8")


def _observe(call):
    global _measurement_ready, _origin, _compute_phase
    # This entire function executes INSIDE the original _timed wall-clock span.
    _compute_phase = 1
    try:
        _origin, cpu_start = time.perf_counter(), time.process_time()
        _measurement["gc_count_before"] = gc.get_count()
        _measurement["threads_before"] = threading.active_count()
        _measurement["caches_before"] = (_vlan_module._admitted_port.cache_info(), _vlan_module._admitted_channel.cache_info())
        _measurement["gc_enabled_before"] = gc.isenabled()
        _measurement["gc_threshold_before"] = gc.get_threshold()
        callable_wall, callable_cpu = time.perf_counter(), time.process_time()
    except Exception as exc:
        _compute_phase = 0
        _measurement["observer_error"] = type(exc).__name__
        _measurement_ready = True
        return call()
    _compute_phase = 2
    try:
        return call()
    finally:
        _compute_phase = 3
        try:
            _measurement["callable_wall_ms"] = 1000 * (time.perf_counter() - callable_wall)
            _measurement["callable_process_cpu_ms"] = 1000 * (time.process_time() - callable_cpu)
            _measurement["gc_count_after"] = gc.get_count()
            _measurement["threads_after"] = threading.active_count()
            _measurement["caches_after"] = (_vlan_module._admitted_port.cache_info(), _vlan_module._admitted_channel.cache_info())
            _measurement["gc_enabled_after"] = gc.isenabled()
            _measurement["gc_threshold_after"] = gc.get_threshold()
            _measurement["wall_ms"] = 1000 * (time.perf_counter() - _origin)
            _measurement["process_cpu_ms"] = 1000 * (time.process_time() - cpu_start)
        except Exception as exc:
            _measurement["observer_error"] = type(exc).__name__
        finally:
            _compute_phase = 0
            _measurement_ready = True


def _invoke_original_compute():
    # Pre-created at plugin import: no extra closure allocation immediately
    # before the original timer which could pull a natural collection outside it.
    return _observe(_active_call)


def _observed_timed(call):
    global _active_call, _armed, _major_frozen
    if not _armed or _phase != "call":
        return _original_timed(call)
    _armed = False
    _active_call = call
    try:
        result = _original_timed(_invoke_original_compute)
        _measurement["original_timer_ms"] = result[1]
        return result  # Preserve the original tuple too; do not allocate a replacement.
    finally:
        # Preserve the preceding window before the later API/ingestion test can
        # rotate it away. No copying or allocation at the compute boundary.
        _major_frozen = True
        _active_call = None


def _census():
    """Only aggregate type/code names, never values, frame locals or payloads."""
    # Finite exact identities avoid invoking arbitrary suite-created metaclass
    # __hash__, __eq__, properties or instance methods while inspecting the heap.
    specs = {
        "_asyncio": ("Task", "Future"), "asyncio.locks": ("Event",),
        "anyio._backends._asyncio": ("CancelScope", "WorkerThread"),
        "tempfile": ("SpooledTemporaryFile",),
        "types": ("TracebackType", "FrameType", "CoroutineType", "GeneratorType", "CellType", "FunctionType"),
        "builtins": ("dict", "list", "tuple", "set"),
        "fastapi.applications": ("FastAPI",), "fastapi.routing": ("APIRoute",),
        "starlette.requests": ("Request",), "_io": ("BytesIO",),
        "webapp.backend.storage": ("Store",), "backend.storage": ("Store",),
        "test_impact_consumers": ("_Graph",),
        "ast": ("Module", "FunctionDef", "AsyncFunctionDef", "ClassDef", "Assign", "AnnAssign",
                "Call", "Name", "Attribute", "Constant", "Expr", "Return", "If", "For", "List",
                "Tuple", "Dict", "arg", "keyword", "Compare", "Subscript", "BinOp", "BoolOp",
                "JoinedStr", "FormattedValue", "With", "Try", "ExceptHandler", "comprehension"),
    }
    classes, labels = {}, []
    for module_name, names in specs.items():
        module = sys.modules.get(module_name)
        namespace = vars(module) if type(module) is types.ModuleType else {}
        for name in names:
            label = module_name + "." + name
            labels.append(label)
            kind = namespace.get(name)
            if kind is not None:
                classes.setdefault(id(kind), []).append(label)
    graph_module = sys.modules.get("test_impact_consumers")
    graph_namespace = vars(graph_module) if type(graph_module) is types.ModuleType else {}
    graph_type = graph_namespace.get("_Graph")
    graph_sizes = []
    counts, frames, tracebacks = Counter(), Counter(), Counter()
    objects = gc.get_objects()
    for obj in objects:
        kind = type(obj)
        for label in classes.get(id(kind), ()):
            counts[label] += 1
        if kind is types.FrameType:
            frames[obj.f_code.co_name] += 1
        elif kind is types.TracebackType:
            tracebacks[obj.tb_frame.f_code.co_name] += 1
        elif kind is graph_type:
            units = tuple.__getitem__(obj, 0)
            if type(units) is dict:
                graph_sizes.append(len(units))
    total = len(objects)
    del objects, obj
    return {
        "phase": "after_both_original_budget_tests", "gc_tracked_total": total,
        "suspect_counts": {name: counts[name] for name in labels},
        "frame_code_counts": frames.most_common(30), "traceback_code_counts": tracebacks.most_common(30),
        "live_threads": threading.active_count(),
        "retained_receipt_graph_unit_counts": sorted(graph_sizes),
    }


def _publish(config, *, phase):
    global _published
    if _published or not _measurement_ready:
        return
    _stop_callback()
    census = _census()
    census["phase"] = phase
    report = {
        "schema": "g14-compute-observation/1", "source": os.environ.get("G14_OBSERVER_SOURCE"),
        "leg": os.environ.get("G14_OBSERVER_LEG"), "measurement": _measurement, "census": census,
        "gc_events": [list(_EVENTS[n * 8:(n + 1) * 8]) for n in range(min(_event_count, _CAPACITY))],
        "gc_event_fields": ["generation", "start_ms", "wall_ms", "process_cpu_ms", "collected", "uncollectable", "stop_ms", "compute_phase"],
        "compute_phase_labels": {0: "outside", 1: "observer_before", 2: "original_callable", 3: "observer_after"},
        "cache_info_fields": ["hits", "misses", "maxsize", "currsize"],
        "callback_error_count": _callback_errors,
        "major_event_count": _major_count,
        "major_history_frozen_after_original_timer": _major_frozen,
        "major_events_evicted": max(0, _major_count - _MAJOR_CAPACITY),
        "recent_major_events": [
            {"node": _MAJOR_NODES[n % _MAJOR_CAPACITY], "phase": _MAJOR_PHASES[n % _MAJOR_CAPACITY],
             "start_relative_to_compute_ms": 1000 * (_MAJORS[(n % _MAJOR_CAPACITY) * 7] - _origin),
             "stop_relative_to_compute_ms": 1000 * (_MAJORS[(n % _MAJOR_CAPACITY) * 7 + 1] - _origin),
             "wall_ms": _MAJORS[(n % _MAJOR_CAPACITY) * 7 + 2],
             "process_cpu_ms": _MAJORS[(n % _MAJOR_CAPACITY) * 7 + 3],
             "collected": _MAJORS[(n % _MAJOR_CAPACITY) * 7 + 4],
             "uncollectable": _MAJORS[(n % _MAJOR_CAPACITY) * 7 + 5],
             "compute_phase": _MAJORS[(n % _MAJOR_CAPACITY) * 7 + 6]}
            for n in range(max(0, _major_count - _MAJOR_CAPACITY), _major_count)
        ],
        "gc_event_count": _event_count, "gc_events_omitted": max(0, _event_count - _CAPACITY),
        "gc_counts_by_generation": list(_COUNTS),
        "gc_wall_ms_by_generation": [1000 * value for value in _TOTAL_WALL],
        "gc_cpu_ms_by_generation": [1000 * value for value in _TOTAL_CPU],
        "observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "imported_sources": {
            label: {"path": str(Path(filename).resolve().relative_to(config.rootpath)),
                    "sha256": hashlib.sha256(Path(filename).read_bytes()).hexdigest()}
            for label, filename in _source_paths.items()
        },
    }
    directory = Path(os.environ["G14_OBSERVER_OUTPUT"])
    (directory / "observation.json").write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    # The file contains individual natural events; the log keeps the same aggregate evidence compact.
    compact = {key: value for key, value in report.items() if key not in ("gc_events", "gc_event_fields")}
    config.pluginmanager.get_plugin("terminalreporter").write_line(
        "G14-COMPUTE-OBSERVATION " + json.dumps(compact, sort_keys=True))
    _published = True


def _safe_publish(config, *, phase):
    # Reporting failure is missing diagnostic evidence, never a replacement for
    # the original test's success/exception. The paired driver retains every log.
    try:
        _publish(config, phase=phase)
    except Exception as exc:
        try:
            config.pluginmanager.get_plugin("terminalreporter").write_line(
                "G14-COMPUTE-OBSERVATION-ERROR " + type(exc).__name__)
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    global _node_id, _phase, _budget_module, _vlan_module, _original_timed, _armed
    if not _enabled:
        return
    _node_id, _phase = item.nodeid, "setup"
    if item.nodeid == _COMPUTE:
        _budget_module = item.module
        _vlan_module = sys.modules[item.module.compute_vlan_carriage.__module__]
        _source_paths["budget"] = item.module.__file__
        _source_paths["compute"] = item.module.compute_vlan_carriage.__code__.co_filename
        _original_timed = item.module._timed
        _armed = True
        item.module._timed = _observed_timed


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    global _phase
    if _enabled:
        _phase = "call"


def _restore_timer():
    if _budget_module is not None and _budget_module._timed is _observed_timed:
        _budget_module._timed = _original_timed


def _stop_callback():
    if _gc_event in gc.callbacks:
        gc.callbacks.remove(_gc_event)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item):
    global _phase
    if not _enabled:
        return
    _phase = "teardown"
    if item.nodeid == _COMPUTE:
        _restore_timer()
    elif item.nodeid == _API:
        _stop_callback()
        _safe_publish(item.config, phase="after_both_budget_calls_before_api_fixture_teardown")


def pytest_sessionfinish(session):
    if _enabled:
        _restore_timer()
        _stop_callback()
        _safe_publish(session.config, phase="session_finish_fallback")
