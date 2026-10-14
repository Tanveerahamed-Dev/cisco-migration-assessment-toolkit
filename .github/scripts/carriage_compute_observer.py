"""Opt-in, reporting-only observer for the unchanged G14 compute budget.

Loaded only by the paired hosted investigation through PYTEST_PLUGINS. The
original _timed implementation still measures the original callable exactly once,
including this observer's small boundary/callback overhead. No collection,
threshold, cache, timer, assertion, selection or test-order policy is changed.
The allocating object census waits until BOTH original budget tests finish.
It counts GC-tracked objects, including unreachable cycles awaiting natural GC;
these are post-target retained-state observations, not proof of live ownership.
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
_EVENTS = array("d", [0.0]) * (_CAPACITY * 7)
_START_WALL = array("d", [0.0]) * 3
_START_CPU = array("d", [0.0]) * 3
_TOTAL_WALL = array("d", [0.0]) * 3
_TOTAL_CPU = array("d", [0.0]) * 3
_COUNTS = array("q", [0]) * 3
_event_count = 0
_origin = 0.0
_measurement = None
_published = False
_source_paths = {}
_active_call = None
_enabled = "G14_OBSERVER_PARENT_PID" not in os.environ
if _enabled:
    os.environ["G14_OBSERVER_PARENT_PID"] = str(os.getpid())


def _gc_event(phase, info):
    global _event_count
    generation = info["generation"]
    wall, cpu = time.perf_counter(), time.process_time()
    if phase == "start":
        _START_WALL[generation], _START_CPU[generation] = wall, cpu
        return
    elapsed, cpu_elapsed = wall - _START_WALL[generation], cpu - _START_CPU[generation]
    _TOTAL_WALL[generation] += elapsed
    _TOTAL_CPU[generation] += cpu_elapsed
    _COUNTS[generation] += 1
    if _event_count < _CAPACITY:
        offset = _event_count * 7
        _EVENTS[offset] = generation
        _EVENTS[offset + 1] = 1000 * (_START_WALL[generation] - _origin)
        _EVENTS[offset + 2] = 1000 * elapsed
        _EVENTS[offset + 3] = 1000 * cpu_elapsed
        _EVENTS[offset + 4] = info["collected"]
        _EVENTS[offset + 5] = info["uncollectable"]
        _EVENTS[offset + 6] = 1000 * (wall - _origin)
    _event_count += 1


def pytest_collection_finish(session):
    """Preserve the real ordered denominator, never sort or reselect it."""
    if not _enabled:
        return
    directory = Path(os.environ["G14_OBSERVER_OUTPUT"])
    directory.mkdir(parents=True, exist_ok=True)
    ordered = [item.nodeid for item in session.items]
    (directory / "collection.json").write_text(json.dumps(ordered), encoding="utf-8")


def _observe(call):
    global _measurement, _origin
    # This entire function executes INSIDE the original _timed wall-clock span.
    from cisco_toolkit import vlan_carriage

    try:
        _origin, cpu_start = time.perf_counter(), time.process_time()
        gc.callbacks.append(_gc_event)
        before = gc.get_count()
        threads_before = threading.active_count()
        caches_before = (vlan_carriage._admitted_port.cache_info(), vlan_carriage._admitted_channel.cache_info())
        enabled, thresholds = gc.isenabled(), gc.get_threshold()
    except Exception as exc:
        if _gc_event in gc.callbacks:
            gc.callbacks.remove(_gc_event)
        _measurement = {"observer_error": type(exc).__name__}
        return call()
    try:
        return call()
    finally:
        try:
            _measurement = {
                "gc_count_before": before, "gc_count_after": gc.get_count(),
                "gc_enabled_before": enabled, "gc_enabled_after": gc.isenabled(),
                "gc_threshold_before": thresholds, "gc_threshold_after": gc.get_threshold(),
                "threads_before": threads_before, "threads_after": threading.active_count(),
                "cache_info_fields": ["hits", "misses", "maxsize", "currsize"],
                "caches_before": caches_before,
                "caches_after": (vlan_carriage._admitted_port.cache_info(), vlan_carriage._admitted_channel.cache_info()),
            }
            _measurement["wall_ms"] = 1000 * (time.perf_counter() - _origin)
            _measurement["process_cpu_ms"] = 1000 * (time.process_time() - cpu_start)
        except Exception as exc:
            _measurement = {"observer_error": type(exc).__name__}
        finally:
            if _gc_event in gc.callbacks:
                gc.callbacks.remove(_gc_event)


def _invoke_original_compute():
    # Pre-created at plugin import: no extra closure allocation immediately
    # before the original timer which could pull a natural collection outside it.
    return _observe(_active_call)


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
    total = len(objects)
    del objects, obj
    return {
        "phase": "after_both_original_budget_tests", "gc_tracked_total": total,
        "suspect_counts": {name: counts[name] for name in labels},
        "frame_code_counts": frames.most_common(30), "traceback_code_counts": tracebacks.most_common(30),
        "live_threads": threading.active_count(),
    }


def _publish(config, *, phase):
    global _published
    if _published or _measurement is None:
        return
    census = _census()
    census["phase"] = phase
    report = {
        "schema": "g14-compute-observation/1", "source": os.environ.get("G14_OBSERVER_SOURCE"),
        "leg": os.environ.get("G14_OBSERVER_LEG"), "measurement": _measurement, "census": census,
        "gc_events": [list(_EVENTS[n * 7:(n + 1) * 7]) for n in range(min(_event_count, _CAPACITY))],
        "gc_event_fields": ["generation", "start_ms", "wall_ms", "process_cpu_ms", "collected", "uncollectable", "stop_ms"],
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if not _enabled:
        yield
        return
    if item.nodeid == _COMPUTE:
        _source_paths["budget"] = item.module.__file__
        _source_paths["compute"] = item.module.compute_vlan_carriage.__code__.co_filename
        original = item.module._timed
        first = True

        def observed_timed(call):
            global _active_call
            nonlocal first
            if not first:
                return original(call)
            first = False
            _active_call = call
            try:
                result, duration = original(_invoke_original_compute)
                _measurement["original_timer_ms"] = duration
                return result, duration
            finally:
                _active_call = None

        item.module._timed = observed_timed
        try:
            yield
        finally:
            item.module._timed = original
    else:
        try:
            yield
        finally:
            if item.nodeid == _API:
                _safe_publish(item.config, phase="after_both_original_budget_tests")


def pytest_sessionfinish(session):
    if _enabled:
        _safe_publish(session.config, phase="session_finish_fallback")
