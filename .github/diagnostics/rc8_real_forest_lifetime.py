"""Hosted actual-caller weak ownership observations, not a performance verdict.

No GC policy is changed. The refuted joint counterfactual is a diagnostic input,
not a proposed product fix. Source contents and object values are never emitted.
"""

import argparse
import ast
from contextlib import contextmanager
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import weakref

SOURCES = {
    "8c4b87d8bc149a30fcd05f5efcd123856a2778e6": "aa003b01248588220d22face7e8218f96a9ada84",
    "a86ee3d7e7890a86cc2a0b5acb10d28562ef09ca": "95863e1d3e83c92cff25b7a012f00aed90a52205",
}
HELPERS = {
    "census": ("tests/client_artifact_census.py", "_Program", "analysis",
               "bfdf7a5dd8ab77b4a1633bb415d7a5898abced9030f56dfd3a061a25aa1e6d06",
               "083347fc256cb830908eec9e2c536d13193c143f5c6172b2433afffba14a548b"),
    "impact": ("tests/test_impact_consumers.py", "_Scan", "_scan",
               "c71e8ccaba9c261530531511320a65bb0a57d6c94198247f2f908717197799f7",
               "5000f441684a1da38b29355730a3f44797c55f9d0d2dce37c9199c174f2edec0"),
}
MAX_REFS, MAX_VISITS, MAX_EDGES, MAX_STACK = 100_000, 2_000_000, 6_000_000, 4096
AST_TYPES = tuple(value for value in vars(ast).values()
                  if type(value) is type and issubclass(value, ast.AST))
SIZERS = ((dict, "dict", dict.__sizeof__), (list, "list", list.__sizeof__),
          (tuple, "tuple", tuple.__sizeof__), (set, "set", set.__sizeof__),
          (frozenset, "frozenset", frozenset.__sizeof__), (str, "str", str.__sizeof__),
          (bytes, "bytes", bytes.__sizeof__), (int, "int", int.__sizeof__),
          (float, "float", float.__sizeof__), (bool, "bool", int.__sizeof__),
          (type(None), "none", object.__sizeof__))
LIMITS = {
    "max_weakrefs": MAX_REFS, "max_graph_visits": MAX_VISITS, "max_graph_edges": MAX_EDGES,
    "max_iterator_stack": MAX_STACK, "no_gc_policy_changes": True,
    "cold_actual_caller_once": True, "intended_module_summary_caches_remain": True,
    "weakrefs_do_not_measure_unreachable_garbage_vs_long_lived_roots": True,
    "sequential_liveness_observations_are_not_atomic_snapshots": True,
    "natural_gc_can_remove_witnesses_before_either_observation": True,
    "observer_allocations_can_change_automatic_gc_phase": True,
    "graph_walk_only_after_both_initial_liveness_observations": True,
    "graph_walk_temporarily_roots_survivors_and_can_change_later_liveness": True,
    "graph_bytes_are_shallow_nonexclusive_and_shared": True,
    "unknown_edges_and_caps_prevent_complete_heap_claim": True,
    "no_full_suite_target_survival_cost_or_acceptance_claim": True,
    "unit_namedtuples_are_not_weakrefable_ast_nodes_observed_instead": True,
    "summary_digest_omitted_to_avoid_serialization_between_lifetime_observations": True,
    "returned_summary_and_cache_containment_not_inspected_at_runtime": True,
    "no_runtime_summary_purity_or_cross_source_equivalence_claim": True,
}


def _git(root, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
                       GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    command = ["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
               "-c", "core.fsmonitor=false", "-C", str(root), *arguments]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("git refused")
    return result.stdout.decode("utf-8").strip()


def _host(subject, output):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15)
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host requirement")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
               for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
        raise ValueError("host requirement")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = workspace / "subject"
    if subject.absolute() != root or subject.resolve(strict=True) != root or root.is_symlink():
        raise ValueError("subject requirement")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if (output.absolute() != output.resolve() or not output.is_relative_to(temporary)
            or output.is_relative_to(root) or os.path.lexists(output)
            or not output.parent.is_dir()):
        raise ValueError("receipt requirement")
    return root, temporary


def _guard(root, source, tree):
    if SOURCES.get(source) != tree or re.fullmatch("[0-9a-f]{40}", source) is None:
        raise ValueError("reviewed source requirement")
    git = root / ".git"
    if git.is_symlink() or not git.is_dir() or git.resolve() != git:
        raise ValueError("repository requirement")
    if (root != Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
            or git != Path(_git(root, "rev-parse", "--absolute-git-dir")).resolve()
            or git != Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()):
        raise ValueError("repository requirement")
    if (_git(root, "rev-parse", "HEAD") != source or _git(root, "rev-parse", "HEAD^{tree}") != tree
            or _git(root, "status", "--porcelain", "--untracked-files=all")):
        raise ValueError("clean source requirement")
    for relative, _constructor, _caller, old, new in HELPERS.values():
        path = root / relative
        if path.is_symlink() or path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("regular helper requirement")
        expected = old if source.startswith("8c4b") else new
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("helper bytes requirement")


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
                    record["flush_error"] = True
            sys.stdout, sys.stderr = streams
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
            record.update(stdout_bytes=os.fstat(stdout.fileno()).st_size,
                          stderr_bytes=os.fstat(stderr.fileno()).st_size)


def _import(root, relative):
    name = "_atlas_real_forest_" + Path(relative).stem
    if name in sys.modules:
        raise ValueError("cold module requirement")
    path = root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("source loader requirement")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path:
        raise ValueError("source filename requirement")
    return module


def _remember(value, label, refs, seen, coverage):
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    if len(refs) >= MAX_REFS:
        coverage["weakref_cap_reached"] = True
        return
    try:
        reference = weakref.ref(value)  # no callback, no hashing of weakrefs or foreign objects
    except TypeError:
        coverage["nonweakrefable"] += 1
        return
    refs.append((label, reference))


def _register(owner, helper, refs, coverage):
    seen = set()
    model = function = node = unit = None
    try:
        _remember(owner, "owner", refs, seen, coverage)
        if helper == "census":
            for model in owner.files:
                _remember(model, "file_model", refs, seen, coverage)
                for function in (model.top, *model.functions):
                    _remember(function, "function_model", refs, seen, coverage)
                    node = function.node
                    _remember(node, "module_ast" if type(node) is ast.Module else "function_ast",
                              refs, seen, coverage)
        else:
            for model in owner.modules.values():
                _remember(model, "module_model", refs, seen, coverage)
                _remember(model.tree, "module_ast", refs, seen, coverage)
                for unit in model.units.values():
                    node = unit.node
                    if type(node) is ast.FunctionDef or type(node) is ast.AsyncFunctionDef:
                        _remember(node, "function_ast", refs, seen, coverage)
    finally:
        owner = model = function = node = unit = None
        seen.clear()


def _alive(refs):
    counts = {}
    value = None
    try:
        for label, reference in refs:
            row = counts.setdefault(label, {"registered": 0, "alive": 0})
            row["registered"] += 1
            value = reference()
            row["alive"] += value is not None
            value = None
        return counts
    finally:
        value = None


def _shape(value, classes):
    kind = type(value)
    for exact, label, size in SIZERS:
        if kind is exact:
            return label, size(value), False
    for exact, label in classes:
        if kind is exact:
            if label == "unit_model":
                return label, tuple.__sizeof__(value), False
            return label, object.__sizeof__(value), True
    for exact in AST_TYPES:
        if kind is exact:
            return "ast", object.__sizeof__(value), True
    return "unknown", None, False


def _forest(refs, classes):
    """One deduplicated graph from survivors; no globals, frames or referrers."""
    counts, seen, stack = {}, set(), []
    value = namespace = None
    edges, unknown, capped = 0, 0, False
    try:
        # Snapshot only weakrefs; resolve one root at a time instead of rooting the forest first.
        for _label, reference in refs:
            value = reference()
            if value is None:
                continue
            stack.append(iter((value,)))
            value = None
            while stack:
                if len(seen) >= MAX_VISITS or edges >= MAX_EDGES:
                    capped = True
                    break
                try:
                    value = next(stack[-1])
                except StopIteration:
                    stack.pop()
                    continue
                edges += 1
                identity = id(value)
                if identity in seen:
                    value = None
                    continue
                seen.add(identity)
                label, size, fields = _shape(value, classes)
                row = counts.setdefault(label, {"count": 0, "shallow_bytes": 0})
                row["count"] += 1
                row["shallow_bytes"] += 0 if size is None else size
                kind = type(value)
                if len(stack) + 2 > MAX_STACK:
                    capped = True
                elif kind is dict:
                    stack.append(iter(dict.keys(value)))
                    stack.append(iter(dict.values(value)))
                elif kind is list or kind is tuple or kind is set or kind is frozenset:
                    stack.append(iter(value))
                elif fields:
                    namespace = object.__getattribute__(value, "__dict__")
                    if type(namespace) is not dict:
                        raise ValueError("known model layout")
                    stack.append(iter((namespace,)))
                elif label == "unit_model":
                    stack.append(tuple.__iter__(value))
                elif label == "unknown":
                    unknown += 1
                value = namespace = None
            if capped:
                break
        return {"unique_objects": len(seen), "examined_edges": edges, "types": counts,
                "unknown_edges": unknown, "traversal_capped": capped,
                "coverage": "partial" if capped or unknown else "known_root_graph_complete"}
    finally:
        value = namespace = None
        stack.clear()
        seen.clear()


def _study(module, root, helper, report):
    _relative, constructor_name, caller_name, _old, _new = HELPERS[helper]
    original, caller = vars(module)[constructor_name], vars(module)[caller_name]
    refs, coverage = [], {"weakref_cap_reached": False, "nonweakrefable": 0, "constructor_calls": 0}
    if helper == "census":
        if vars(module)["_ANALYSES"]:
            raise ValueError("cold summary requirement")
        classes = [(original, "owner"), (module._File, "file_model"),
                   (module._Function, "function_model"), (module._Imports, "imports_model")]
    else:
        if caller.cache_info().currsize:
            raise ValueError("cold summary requirement")
        classes = [(original, "owner"), (module._Module, "module_model"), (module._Unit, "unit_model")]

    def observed(*arguments, **keywords):
        coverage["constructor_calls"] += 1
        if coverage["constructor_calls"] != 1:
            raise ValueError("single construction requirement")
        instance = original(*arguments, **keywords)
        _register(instance, helper, refs, coverage)
        return instance

    report["gc_before"] = {"counts": gc.get_count(), "stats": gc.get_stats()}
    started = time.monotonic()
    vars(module)[constructor_name] = observed
    _caller_result = None
    try:
        _caller_result = caller(root)
        report["after_caller_return"] = _alive(refs)
        _caller_result = None
        report["after_result_drop"] = _alive(refs)
    finally:
        _caller_result = None
        vars(module)[constructor_name] = original
    report["caller_seconds_including_observation"] = time.monotonic() - started
    report["gc_after_initial_observations"] = {"counts": gc.get_count(), "stats": gc.get_stats()}
    report["witness_coverage"] = coverage
    if coverage["constructor_calls"] != 1 or not refs:
        raise ValueError("actual constructor not observed")
    report["forest_after_initial_observations"] = _forest(refs, classes)
    refs.clear()
    report["gc_after_graph"] = {"counts": gc.get_count(), "stats": gc.get_stats()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--helper", choices=HELPERS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = {"status": "refused", "stage": "host_guard", "limits": LIMITS}
    output = None
    try:
        root, temporary = _host(arguments.subject, arguments.output)
        output = arguments.output
        report["stage"] = "source_guard"
        _guard(root, arguments.source, arguments.expected_tree)
        report.update(source=arguments.source, tree=arguments.expected_tree, helper=arguments.helper)
        report["helper_file"] = HELPERS[arguments.helper][0]
        report["helper_sha256"] = hashlib.sha256((root / report["helper_file"]).read_bytes()).hexdigest()
        report["captured_output"] = {}
        report["stage"] = "private_import"
        sys.path[:0] = [str(root / "tests"), str(root)]
        with _capture(temporary, report["captured_output"]):
            module = _import(root, report["helper_file"])
            report["stage"] = "actual_caller"
            _study(module, root, arguments.helper, report)
        report["stage"] = "final_source_guard"
        _guard(root, arguments.source, arguments.expected_tree)
        graph = report["forest_after_initial_observations"]
        partial = (report["witness_coverage"]["weakref_cap_reached"]
                   or report["witness_coverage"]["nonweakrefable"] > 0
                   or graph["coverage"] == "partial")
        report["residual_observation"] = ("survivors_observed" if any(
            row["alive"] for row in report["after_result_drop"].values()) else "no_survivors_observed")
        report["status"] = "observed_partial" if partial else "observed_known_roots"
        report["stage"] = "complete"
        exit_code = 0
    except Exception:
        exit_code = 1  # fixed stage/status only: no exception strings, source or object values
    if output is None:
        print('{"status":"host_or_receipt_refused"}')
        return exit_code
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError:
        print('{"status":"receipt_write_refused"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
