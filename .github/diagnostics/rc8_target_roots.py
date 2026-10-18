"""Hosted TARGET observation only; instrumented latency is not acceptance evidence.

Environment: ATLAS_TARGET_ROOTS_REPORT, ATLAS_TARGET_ROOTS_SOURCE_ROOT,
ATLAS_TARGET_ROOTS_SOURCE, ATLAS_TARGET_ROOTS_TREE. No collection or GC policy
is changed. The old native failures and refuted counterfactual remain evidence.
"""

import ast
import gc
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import types

import pytest

SOURCE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
TREE = "aa003b01248588220d22face7e8218f96a9ada84"
TARGET = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
FILES = {
    "tests/test_operator_evidence_contract.py": "3459bb6c3954b110c460d7720b911454afe14abfeb37bb15500f4a6f44063f0d",
    "tests/client_artifact_census.py": "bfdf7a5dd8ab77b4a1633bb415d7a5898abced9030f56dfd3a061a25aa1e6d06",
    "tests/test_impact_consumers.py": "c71e8ccaba9c261530531511320a65bb0a57d6c94198247f2f908717197799f7",
}
SITES = {
    "operator_enclosing_visit": ("tests/test_operator_evidence_contract.py", 553,
                                 "_enclosing_functions.<locals>.visit", ("owner", "visit"), "owner", dict),
    "census_load_visit": ("tests/client_artifact_census.py", 476,
                          "_load_file.<locals>.visit", ("functions", "module", "relative", "visit"), "functions", list),
    "impact_units_visit": ("tests/test_impact_consumers.py", 256,
                           "_units.<locals>.visit", ("bindings", "fresh", "units", "visit"), "units", dict),
}
MAX_OBJECTS, MAX_ROOTS = 3_000_000, 20_000
MAX_VISITS, MAX_EDGES, MAX_DEPTH = 2_000_000, 6_000_000, 4096
LIMITS = {
    "max_objects_inspected": MAX_OBJECTS, "max_unique_roots_per_site": MAX_ROOTS,
    "max_graph_unique_visits_per_site": MAX_VISITS, "max_graph_edges_per_site": MAX_EDGES,
    "max_graph_iterator_depth": MAX_DEPTH, "snapshot_creation_uncapped": True,
    "snapshot_includes_pending_garbage_and_observer_references": True,
    "untracked_objects_missing": True, "type_census_is_not_complete_heap_ownership": True,
    "only_three_named_closure_sites_examined": True,
    "targeted_sites_not_subject_to_generic_top_cells_or_slot_caps": True,
    "root_graphs_deduplicated_separately_and_nonexclusive": True,
    "shallow_bytes_do_not_measure_exclusive_retention": True,
    "snapshot_and_graph_walk_temporarily_root_observed_objects": True,
    "observer_allocations_and_json_emission_can_change_gc_phase_and_mask_latency": True,
    "all_observed_object_references_cleared_before_test_body": True,
    "no_gc_policy_or_test_collection_order_timer_assertion_changes": True,
    "no_frame_positions_locals_referrers_or_function_globals": True,
    "presence_does_not_establish_long_lived_owner_or_timing_cause": True,
    "source_position_matches_do_not_prove_runtime_code_or_ownership": True,
    "instrumented_timings_are_not_acceptance": True,
}

# Capture exact primitives before tests can patch modules. Foreign types are
# looked up by integer identity, never hashed, sized, named, iterated or repr'd.
_TYPE, _ID, _LEN, _ITER, _NEXT = type, id, len, iter, next
_STR, _INT = str, int
_DICT, _LIST, _TUPLE, _SET, _FROZENSET = dict, list, tuple, set, frozenset
_DICT_GET, _DICT_KEYS, _DICT_VALUES = dict.get, dict.keys, dict.values
_FUNCTION, _CODE, _CELL, _MODULE = types.FunctionType, types.CodeType, types.CellType, types.ModuleType
_GETSET = types.GetSetDescriptorType
_GETSET_GET = types.GetSetDescriptorType.__get__
_MODULE_GET, _TYPE_GET = types.ModuleType.__getattribute__, type.__getattribute__
_AST_DICT = ast.AST.__dict__["__dict__"]
_SENTINEL = object()
_PYTEST_FUNCTION = pytest.Function
_GET_OBJECTS, _GET_STATS, _GET_COUNT = gc.get_objects, gc.get_stats, gc.get_count
_WRITE, _CLOSE, _CLOCK, _RUN = os.write, os.close, time.monotonic, subprocess.run
_MODULES = sys.modules
_EMPTY_MODELS = {}
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False).encode
_SHAPES = {}
for _exact, _label, _size in (
    (dict, "dict", dict.__sizeof__), (list, "list", list.__sizeof__),
    (tuple, "tuple", tuple.__sizeof__), (set, "set", set.__sizeof__),
    (frozenset, "frozenset", frozenset.__sizeof__), (str, "str", str.__sizeof__),
    (bytes, "bytes", bytes.__sizeof__), (bytearray, "bytearray", bytearray.__sizeof__),
    (int, "int", int.__sizeof__), (float, "float", float.__sizeof__),
    (bool, "bool", int.__sizeof__), (type(None), "none", object.__sizeof__),
    (types.FunctionType, "function", object.__sizeof__), (types.CellType, "cell", object.__sizeof__),
    (types.FrameType, "frame", types.FrameType.__sizeof__), (types.CodeType, "code", types.CodeType.__sizeof__),
    (types.TracebackType, "traceback", object.__sizeof__), (types.ModuleType, "module", object.__sizeof__),
):
    _SHAPES[_ID(_exact)] = (_exact, _label, _size, None)
for _exact in vars(ast).values():
    if _TYPE(_exact) is type and issubclass(_exact, ast.AST):
        _SHAPES[_ID(_exact)] = (_exact, "ast." + _TYPE_GET(_exact, "__name__"), object.__sizeof__, _AST_DICT)
del _exact, _label, _size
_STATE = {"fd": None, "ready": False, "seen": False, "root": None, "bindings": {}, "metadata": {}}


def _git(root, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_NO_REPLACE_OBJECTS="1")
    result = _RUN(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c",
                   "core.fsmonitor=false", "-C", str(root), *arguments], env=environment,
                  capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("source guard refused")
    return result.stdout.decode("utf-8").strip()


def _guard(root):
    git = root / ".git"
    if git.is_symlink() or not git.is_dir() or git.resolve() != git:
        raise ValueError("source guard refused")
    if (Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root
            or Path(_git(root, "rev-parse", "--absolute-git-dir")).resolve() != git
            or Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != git
            or _git(root, "rev-parse", "HEAD") != SOURCE or _git(root, "rev-parse", "HEAD^{tree}") != TREE
            or _git(root, "status", "--porcelain", "--untracked-files=no")):
        raise ValueError("source guard refused")
    for relative, digest in FILES.items():
        path = root / relative
        if (path.is_symlink() or path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError("source helper refused")
    plugin = Path(__file__).resolve(strict=True)
    return hashlib.sha256(plugin.read_bytes()).hexdigest()


def _shape(value, models):
    kind = _TYPE(value)
    row = _DICT_GET(_SHAPES, _ID(kind))
    if row is not None and row[0] is kind:
        return row
    row = _DICT_GET(models, _ID(kind))
    if row is not None and row[0] is kind:
        return row
    return (None, "unknown", None, None)


def _model_shapes(root):
    """Read only explicit source-bound dataclasses and the impact tuple model."""
    shapes, reports = {}, {}
    for module_name, relative, names in (
        ("client_artifact_census", "tests/client_artifact_census.py", ("_Function", "_File", "_Imports")),
        ("test_impact_consumers", "tests/test_impact_consumers.py", ("_Unit",)),
    ):
        module = _DICT_GET(_MODULES, module_name)
        if module is None:
            reports[module_name] = {"status": "absent", "validated_classes": 0, "refused_classes": 0}
            continue
        record = {"status": "unvalidated", "validated_classes": 0, "refused_classes": _LEN(names)}
        reports[module_name] = record
        if _TYPE(module) is not _MODULE:
            continue
        namespace = _MODULE_GET(module, "__dict__")
        filename = _DICT_GET(namespace, "__file__")
        path = root / relative
        if (_TYPE(filename) is not str or filename != str(path) or path.is_symlink()
                or path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode)
                or hashlib.sha256(path.read_bytes()).hexdigest() != FILES[relative]):
            continue
        for name in names:
            model = _DICT_GET(namespace, name)
            if _TYPE(model) is not type:
                continue
            fields = _TYPE_GET(model, "__dict__")
            descriptor = fields.get("__dict__")
            bases = _TYPE_GET(model, "__bases__")
            source_module, qualname = _TYPE_GET(model, "__module__"), _TYPE_GET(model, "__qualname__")
            if (_TYPE(source_module) is not str or _TYPE(qualname) is not str
                    or source_module != module_name or qualname != name or _LEN(bases) != 1):
                continue
            if name == "_Unit":
                if bases[0] is not tuple:
                    continue
                shapes[_ID(model)] = (model, "model._Unit", tuple.__sizeof__, None)
            else:
                if (bases[0] is not object or _TYPE(descriptor) is not _GETSET
                        or descriptor.__objclass__ is not model or descriptor.__name__ != "__dict__"):
                    continue
                shapes[_ID(model)] = (model, "model." + name, object.__sizeof__, descriptor)
            record["validated_classes"] += 1
            record["refused_classes"] -= 1
        record["status"] = "validated" if record["refused_classes"] == 0 else "partial"
    return shapes, reports


def _site(function, bindings):
    code = function.__code__
    if _TYPE(code) is not _CODE:
        return None
    if (_TYPE(code.co_filename) is not _STR or _TYPE(code.co_name) is not _STR
            or _TYPE(code.co_qualname) is not _STR or _TYPE(code.co_firstlineno) is not _INT
            or _TYPE(code.co_freevars) is not _TUPLE):
        return "unsafe_code_metadata"
    for name in code.co_freevars:
        if _TYPE(name) is not _STR:
            return "unsafe_code_metadata"
    for label, binding in bindings.items():
        if (code.co_filename == binding["filename"] and code.co_firstlineno == binding["line"]
                and code.co_name == "visit" and code.co_qualname == binding["qualname"]):
            return label if code.co_freevars == binding["freevars"] else "binding_mismatch"
    return None


def _summarize(snapshot, bindings, models, max_objects=MAX_OBJECTS, max_roots=MAX_ROOTS):
    counts, sites, roots, root_ids = {}, {}, {}, {}
    for label, binding in bindings.items():
        sites[label] = {"relative": binding["relative"], "line": binding["line"],
                        "qualname": binding["qualname"], "freevars": binding["freevars"],
                        "matched_functions": 0, "slots": {}, "wrong_root_type": 0,
                        "roots_omitted_by_cap": 0, "unique_roots": 0}
        roots[label], root_ids[label] = [], _SET()
    mismatch, unsafe, inspected = 0, 0, min(_LEN(snapshot), max_objects)
    value = code = closure = cell = content = None
    try:
        for index in range(inspected):
            value = snapshot[index]
            shape = _shape(value, _EMPTY_MODELS)  # census uses builtin/AST identities only
            counts[shape[1]] = counts.get(shape[1], 0) + 1
            if _TYPE(value) is not _FUNCTION:
                continue
            label = _site(value, bindings)
            if label == "unsafe_code_metadata":
                unsafe += 1
                continue
            if label == "binding_mismatch":
                mismatch += 1
                continue
            if label is None:
                continue
            binding, row = bindings[label], sites[label]
            row["matched_functions"] += 1
            code, closure = value.__code__, value.__closure__
            if _TYPE(closure) is not _TUPLE or _LEN(closure) != _LEN(code.co_freevars):
                mismatch += 1
                continue
            for slot, name in enumerate(code.co_freevars):
                cell = closure[slot]
                slot_counts = row["slots"].setdefault(name, {})
                if _TYPE(cell) is not _CELL:
                    slot_counts["invalid_cell"] = slot_counts.get("invalid_cell", 0) + 1
                    continue
                try:
                    content = cell.cell_contents
                except ValueError:
                    slot_counts["empty_cell"] = slot_counts.get("empty_cell", 0) + 1
                    continue
                kind = _shape(content, models)[1]
                slot_counts[kind] = slot_counts.get(kind, 0) + 1
                if name == binding["root_name"]:
                    if _TYPE(content) is not binding["root_type"]:
                        row["wrong_root_type"] += 1
                    elif _ID(content) not in root_ids[label]:
                        root_ids[label].add(_ID(content))
                        if _LEN(roots[label]) < max_roots:
                            roots[label].append(content)
                        else:
                            row["roots_omitted_by_cap"] += 1
                content = cell = None
        for label in sites:
            sites[label]["unique_roots"] = _LEN(root_ids[label])
        return ({"snapshot_total": _LEN(snapshot), "inspected": inspected,
                 "uninspected_tail": _LEN(snapshot) - inspected,
                 "census_complete_for_snapshot": inspected == _LEN(snapshot),
                 "type_counts": counts, "targeted_sites": sites,
                 "target_code_binding_mismatches": mismatch,
                 "unsafe_code_metadata_count": unsafe,
                 "target_search_complete_for_inspected_functions": unsafe == 0 and mismatch == 0}, roots)
    finally:
        value = code = closure = cell = content = None
        for identities in root_ids.values():
            identities.clear()
        root_ids.clear()


def _walk(roots, models, visits=MAX_VISITS, edges=MAX_EDGES, depth=MAX_DEPTH):
    seen, stack, counts = _SET(), [_ITER(roots)], {}
    value = namespace = None
    examined, unknown, capped = 0, 0, False
    try:
        while stack:
            if examined >= edges or _LEN(seen) >= visits:
                capped = True
                break
            value = _NEXT(stack[-1], _SENTINEL)
            if value is _SENTINEL:
                stack.pop()
                continue
            examined += 1
            identity = _ID(value)
            if identity in seen:
                value = None
                continue
            seen.add(identity)
            _exact, label, size, descriptor = _shape(value, models)
            row = counts.setdefault(label, {"count": 0, "shallow_bytes": 0})
            row["count"] += 1
            row["shallow_bytes"] += 0 if size is None else size(value)
            kind = _TYPE(value)
            if _LEN(stack) + 2 > depth:
                capped = True
                continue
            if kind is _DICT:
                stack.append(_ITER(_DICT_KEYS(value)))
                stack.append(_ITER(_DICT_VALUES(value)))
            elif kind is _LIST or kind is _TUPLE or kind is _SET or kind is _FROZENSET:
                stack.append(_ITER(value))
            elif label == "model._Unit":
                stack.append(tuple.__iter__(value))
            elif descriptor is not None:
                namespace = _GETSET_GET(descriptor, value, _TYPE(value))
                if _TYPE(namespace) is not _DICT:
                    raise ValueError("known node layout refused")
                stack.append(_ITER((namespace,)))
            elif label == "unknown":
                unknown += 1
            value = namespace = None
        return {"unique_visits": _LEN(seen), "edges_examined": examined, "types": counts,
                "unknown_edges": unknown, "traversal_capped": capped,
                "coverage": "partial" if capped or unknown else "known_roots_complete"}
    finally:
        value = namespace = None
        stack.clear()
        seen.clear()


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
            _WRITE(2, b"RC8 target diagnostic report refused; product outcome unchanged.\n")
        except Exception:
            pass


def _observe():
    snapshot, roots, models = None, {}, {}
    report = {"status": "observation_error", "limits": LIMITS, **_STATE["metadata"]}
    started, before = _CLOCK(), {"stats": _GET_STATS(), "counts": _GET_COUNT()}
    try:
        models, model_binding = _model_shapes(_STATE["root"])
        snapshot = _GET_OBJECTS()  # exactly one uncapped creation
        census, roots = _summarize(snapshot, _STATE["bindings"], models)
        graphs = {label: _walk(owners, models) for label, owners in roots.items()}
        report.update(status="observed", census=census, root_graphs=graphs, model_binding=model_binding)
    except Exception:
        pass
    finally:
        for owners in roots.values():
            owners.clear()
        roots.clear()
        models.clear()
        if snapshot is not None:
            snapshot.clear()
        snapshot = None
    report["gc_before"] = before
    report["gc_after"] = {"stats": _GET_STATS(), "counts": _GET_COUNT()}
    report["observation_seconds"] = _CLOCK() - started
    try:
        if _guard(_STATE["root"]) != _STATE["metadata"]["plugin_sha256"]:
            raise ValueError("plugin bytes changed")
        report["source_guard_after"] = "pass"
    except Exception:
        report["status"], report["source_guard_after"] = "source_guard_refused", "refused"
    _emit(report)


def pytest_configure(config):
    try:
        if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
                or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15)):
            raise ValueError("host refused")
        if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
                   for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
            raise ValueError("host refused")
        workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        root = workspace / "subject"
        requested = Path(os.environ["ATLAS_TARGET_ROOTS_SOURCE_ROOT"])
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        output = Path(os.environ["ATLAS_TARGET_ROOTS_REPORT"])
        if (requested.absolute() != root or requested.resolve(strict=True) != root or root.is_symlink()
                or output.absolute() != output.resolve() or not output.is_relative_to(temporary)
                or output.is_relative_to(root) or os.path.lexists(output)
                or os.environ.get("ATLAS_TARGET_ROOTS_SOURCE") != SOURCE
                or os.environ.get("ATLAS_TARGET_ROOTS_TREE") != TREE):
            raise ValueError("binding refused")
        _STATE["fd"] = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        plugin_digest = _guard(root)
        _STATE["root"] = root
        _STATE["metadata"] = {"source": SOURCE, "tree": TREE, "source_guard_before": "pass",
                              "plugin_sha256": plugin_digest, "helper_sha256": FILES,
                              "operator_git_blob": "86f2318d0202363c12dbba7032d93970cf4ab74c"}
        _STATE["bindings"] = {
            label: {"relative": relative, "filename": str(root / relative), "line": line,
                    "qualname": qualname, "freevars": freevars, "root_name": root_name, "root_type": root_type}
            for label, (relative, line, qualname, freevars, root_name, root_type) in SITES.items()
        }
        _STATE["ready"] = True
    except Exception:
        if _STATE["fd"] is not None:
            _emit({"status": "configuration_refused", "limits": LIMITS})


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_setup(item):
    outcome = yield
    if (_STATE["ready"] and not _STATE["seen"] and outcome.excinfo is None
            and _TYPE(item) is _PYTEST_FUNCTION and item.nodeid == TARGET):
        _STATE["seen"] = True
        try:
            _observe()
        except Exception:
            _emit({"status": "observation_error", "limits": LIMITS})


def pytest_unconfigure(config):
    if _STATE["fd"] is not None:
        try:
            if _STATE["ready"] and not _STATE["seen"]:
                _emit({"status": "target_not_observed", "limits": LIMITS})
        finally:
            try:
                _CLOSE(_STATE["fd"])
            except OSError:
                pass
            _STATE["fd"] = None
            _STATE["bindings"].clear()
