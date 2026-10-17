"""GitHub-only synthetic lifetime/equivalence proof; no production modification.

This imports each reviewed source helper once. Only the replacement function is
compiled into copied globals. Natural GC is never controlled; missing original
retention is explicitly inconclusive. No full-suite performance claim follows.
"""

from __future__ import annotations

import __future__
import argparse
import ast
from collections import Counter
from contextlib import contextmanager
from copy import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import weakref

HEAD = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
TREE = "aa003b01248588220d22face7e8218f96a9ada84"
PAIRS = {"tests/client_artifact_census.py": "_load_file", "tests/test_impact_consumers.py": "_units"}
FIELDS = {"path", "function", "source_sha256", "old", "new", "candidate_sha256"}
CASES = {
    "nested_async_defaults": """import os as local_os
from synthetic_package import member as alias
VALUE = {'public': [1, 2]}
def outer(a=VALUE, *, b=(1, 2)):
    assigned = local_os.path.join('public', 'file')
    class Inner:
        async def method(self, x=alias):
            async def inner(y=x):
                return y
            return await inner()
    def nested(z=assigned):
        return z
    return Inner, nested
""",
    "compound_redefinitions": """if True:
    def repeated(value=1):
        return value
else:
    def repeated(value=2):
        return value
try:
    class Container:
        class Nested:
            def method(self):
                return 'public'
except Exception:
    async def fallback():
        return None
""",
    "repeated_nested_model_keys": """def repeated(value=1):
    def inner(arg=value):
        return arg
    return inner
def repeated(value=2):
    class Nested:
        def method(self):
            return value
    def inner(arg=value):
        return arg
    return Nested, inner
""",
    "assignments_calls_annotations": """from synthetic_package import producer
items: list[int] = [1, 2, 3]
first, second = producer()
class Example:
    field = items
    @producer('public')
    def method(self, value: int = producer(3), *args, enabled=True, **kwargs):
        target = producer(value)
        target += 1
        return [target for ignored in args]
""",
}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
                            check=True, timeout=60)
    return result.stdout.decode("utf-8").strip()


def _guard(root, changes):
    if _git(root, "rev-parse", "HEAD") != HEAD or _git(root, "rev-parse", "HEAD^{tree}") != TREE:
        raise ValueError("subject identity")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("subject tracked changes")
    if type(changes) is not list or len(changes) != len(PAIRS):
        raise ValueError("change count")
    guarded, seen = [], set()
    for change in changes:
        if type(change) is not dict or set(change) != FIELDS or any(type(v) is not str for v in change.values()):
            raise ValueError("change schema")
        relative, function = change["path"], change["function"]
        if relative not in PAIRS or function != PAIRS[relative] or relative in seen:
            raise ValueError("helper identity")
        seen.add(relative)
        source = (root / relative).read_bytes()
        text = source.decode("utf-8")
        if _digest(source) != change["source_sha256"] or text.count(change["old"]) != 1:
            raise ValueError("source or snippet identity")
        full_tree = ast.parse(text)
        owner = next(node for node in full_tree.body if isinstance(node, ast.FunctionDef) and node.name == function)
        if ast.get_source_segment(text, owner) != change["old"].rstrip("\r\n"):
            raise ValueError("whole function required")
        for name in ("old", "new"):
            nodes = ast.parse(change[name]).body
            if len(nodes) != 1 or type(nodes[0]) is not ast.FunctionDef or nodes[0].name != function:
                raise ValueError("single function required")
            if nodes[0].decorator_list:
                raise ValueError("decorators unsupported")
        candidate = text.replace(change["old"], change["new"], 1).encode("utf-8")
        if _digest(candidate) != change["candidate_sha256"]:
            raise ValueError("candidate identity")
        guarded.append(change)
    return guarded


@contextmanager
def _capture_imports(stats):
    """Capture Python/native fd output privately; emit byte counts, never text."""
    streams = sys.stdout, sys.stderr
    for stream in streams:
        stream.flush()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
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
                    stats["flush_error"] = True
            sys.stdout, sys.stderr = streams
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
            stats["stdout_bytes"] = os.fstat(stdout.fileno()).st_size
            stats["stderr_bytes"] = os.fstat(stderr.fileno()).st_size


def _import_original(root, relative, stats):
    name = Path(relative).stem
    if name in sys.modules:
        raise ValueError("helper already imported")
    path = root / relative
    before = len(sys.modules)
    try:
        with _capture_imports(stats):
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ValueError("source loader")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module  # required for the actual module's dataclasses
            spec.loader.exec_module(module)
    finally:
        stats["added_modules"] = len(sys.modules) - before
    stats["source_file_preserved"] = Path(module.__file__).resolve() == path
    if not stats["source_file_preserved"]:
        raise ValueError("source file changed")
    return module


def _candidate(module, change):
    namespace = dict(vars(module))
    code = compile(change["new"], module.__file__, "exec",
                   flags=__future__.annotations.compiler_flag, dont_inherit=True)
    exec(code, namespace)
    return namespace[change["function"]]


def _compile_contract(original, candidate):
    left, right = original.__code__, candidate.__code__
    slots = left.co_argcount + left.co_kwonlyargcount
    return (left.co_flags == right.co_flags and left.co_argcount == right.co_argcount
            and left.co_posonlyargcount == right.co_posonlyargcount
            and left.co_kwonlyargcount == right.co_kwonlyargcount
            and left.co_varnames[:slots] == right.co_varnames[:slots]
            and original.__annotations__ == candidate.__annotations__
            and original.__defaults__ == candidate.__defaults__
            and original.__kwdefaults__ == candidate.__kwdefaults__)


def _call(function, name, root, label, source):
    if name == "_load_file":
        return function(root, f"synthetic/{label}.py")
    tree = ast.parse(source, filename=f"synthetic/{label}.py")
    return function(tree)


def _lifetime(function, name, root, label, source):
    """No normalization, hashing or serialization occurs before the weakref read."""
    started = time.monotonic()
    tree = result = owner = None
    if name == "_load_file":
        result = function(root, f"synthetic/{label}.py")
        owner = result.functions[0]
        owner_kind = "_Function"
    else:
        tree = ast.parse(source, filename=f"synthetic/{label}.py")
        result = function(tree)
        owner = result[0]["<module>"].node
        owner_kind = "ast.Module"
    reference = weakref.ref(owner)
    tree = result = owner = None
    alive = reference() is not None
    reference = None
    return {"owner_kind": owner_kind, "alive_after_drop": alive,
            "seconds": time.monotonic() - started}


def _ast_records(tree):
    nodes, identities = [], {}
    for node in ast.walk(tree):
        if id(node) not in identities:
            identities[id(node)] = len(nodes)
            nodes.append(node)
    records = []
    for node in nodes:
        records.append({"kind": type(node).__name__,
                        "fields": [[name, _field(value, identities)] for name, value in ast.iter_fields(node)],
                        "attributes": [[name, getattr(node, name)] for name in node._attributes
                                       if hasattr(node, name)]})
    return identities, records


def _field(value, identities):
    if isinstance(value, ast.AST):
        return {"ast_node": identities[id(value)]}
    if type(value) in (list, tuple):
        return [_field(item, identities) for item in value]
    if value is None or type(value) in (str, int, bool, float):
        return value
    raise ValueError("unsupported synthetic AST field")


def _assignments(mapping, identities):
    return [[key, [_field(node, identities) for node in values]] for key, values in mapping.items()]


def _normalize(result, name):
    tree = result.top.node if name == "_load_file" else result[0]["<module>"].node
    identities, records = _ast_records(tree)
    if name == "_load_file":
        order = [result.top, *result.functions]
        models, model_ids = [], {}
        for function in order:
            if id(function) not in model_ids:
                model_ids[id(function)] = len(models)
                models.append(function)
        functions = []
        for function in models:
            functions.append({"key": function.key, "module": function.module, "qualname": function.qualname,
                              "node": _field(function.node, identities), "parameters": sorted(function.parameters),
                              "enclosing_model": None if function.enclosing is None else model_ids[id(function.enclosing)],
                              "assignments": _assignments(function.assignments, identities),
                              "calls": [_field(node, identities) for node in function.calls],
                              "references": [[_field(node, identities), _field(call, identities)]
                                             for node, call in function.references]})
        normalized = {"relative": result.relative, "module": result.module,
                      "imports": [list(result.imports.modules.items()), list(result.imports.names.items())],
                      "assignments": _assignments(result.module_assignments, identities), "functions": functions,
                      "module_assignments_is_top_assignments": result.module_assignments is result.top.assignments,
                      "returned_model_order": [model_ids[id(function)] for function in order]}
        units = len(functions)
    else:
        unit_map, bindings, skip = result
        normalized = {"units": [[key, [unit.name, _field(unit.node, identities), unit.kind, unit.scope, unit.cls,
                                      _field(unit.roots, identities)]] for key, unit in unit_map.items()],
                      "bindings": [[scope, [[key, list(values)] for key, values in mapping.items()]]
                                   for scope, mapping in bindings.items()],
                      "skip_nodes": sorted(identities[identity] for identity in skip)}
        units = len(unit_map)
    normalized["ast"] = records
    raw = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"structural_sha256": _digest(raw), "ast_nodes": len(records), "units": units,
            "ast_kinds": dict(sorted(Counter(row["kind"] for row in records).items()))}


def _equivalence(original, candidate, name, root, label, source):
    left = _call(original, name, root, label, source)
    left_summary = _normalize(left, name)
    left = None
    right = _call(candidate, name, root, label, source)
    right_summary = _normalize(right, name)
    right = None
    return {"equal": left_summary == right_summary, "original": left_summary, "candidate": right_summary}


def _alias_sanity(original, root):
    """Fresh synthetic owners, after witnesses: exercise the actual detached-parent counterexample."""
    label = "repeated_nested_model_keys"
    result = _call(original, "_load_file", root, label, CASES[label])
    baseline = _normalize(result, "_load_file")
    child = next(function for function in result.functions if function.enclosing is not None)
    parent = child.enclosing
    detached = copy(parent)
    child.enclosing = detached
    refused = False
    try:
        try:
            _normalize(result, "_load_file")
        except KeyError:
            refused = True  # detached identity cannot be silently represented by its identical key
    finally:
        child.enclosing = parent
    result.module_assignments = dict(result.module_assignments)
    alias_detected = _normalize(result, "_load_file") != baseline
    result = child = parent = detached = None
    return {"detached_same_key_parent_refused": refused, "module_assignments_alias_difference_detected": alias_detected}


def _prove(root, changes, report):
    saved_path, saved_bytecode = list(sys.path), sys.dont_write_bytecode
    sys.path[:0] = [str(root / "tests"), str(root)]
    sys.dont_write_bytecode = True
    try:
        with tempfile.TemporaryDirectory(prefix="rc8-ast-synthetic-") as temporary:
            fixtures = Path(temporary)
            (fixtures / "synthetic").mkdir()
            for label, source in CASES.items():
                (fixtures / "synthetic" / f"{label}.py").write_text(source, encoding="utf-8", newline="\n")
            for change in changes:
                record = {key: change[key] for key in ("path", "function", "source_sha256", "candidate_sha256")}
                record["imports"], record["cases"] = {}, []
                report["helpers"].append(record)
                report["stage"] = "import_original"
                module = _import_original(root, change["path"], record["imports"])
                original, candidate = getattr(module, change["function"]), _candidate(module, change)
                record["compile_contract_equal"] = _compile_contract(original, candidate)
                if not record["compile_contract_equal"]:
                    raise ValueError("outer compile contract")
                for label, source in CASES.items():
                    report["stage"] = "lifetime"
                    old_life = _lifetime(original, change["function"], fixtures, label, source)
                    new_life = _lifetime(candidate, change["function"], fixtures, label, source)
                    case = {"synthetic_case": label, "original_lifetime": old_life, "candidate_lifetime": new_life}
                    record["cases"].append(case)
                    case["lifetime_status"] = ("candidate_retained" if new_life["alive_after_drop"] else
                                               "differential" if old_life["alive_after_drop"] else "inconclusive")
                    report["stage"] = "fresh_structural_equivalence"
                    case["equivalence"] = _equivalence(original, candidate, change["function"], fixtures, label, source)
                if change["function"] == "_load_file":
                    report["stage"] = "model_alias_negative_controls"
                    record["alias_negative_controls"] = _alias_sanity(original, fixtures)
                    if not all(record["alias_negative_controls"].values()):
                        raise ValueError("model alias negative control")
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True, type=Path)
    parser.add_argument("--changes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.version_info[:3] != (3, 12, 15):
        raise SystemExit("requires GitHub Actions and Python 3.12.15")
    root, output = arguments.subject.resolve(), arguments.output.resolve()
    if output.is_relative_to(root):
        raise SystemExit("report must be outside subject")
    report = {"status": "probe_error", "stage": "source_guard", "source": HEAD, "tree": TREE, "helpers": [],
              "limits": {"synthetic_equivalence_only": True, "natural_gc_can_erase_original_witness": True,
                         "no_gc_policy_changes": True, "no_primary_source_modification": True,
                         "no_full_suite_cause_or_acceptance_claim": True}}
    try:
        changes = _guard(root, json.loads(arguments.changes.read_bytes()))
        _prove(root, changes, report)
        report["stage"] = "source_guard_after_imports_and_probes"
        _guard(root, changes)
        cases = [case for helper in report["helpers"] for case in helper["cases"]]
        if any(not case["equivalence"]["equal"] or case["lifetime_status"] == "candidate_retained" for case in cases):
            report["status"], exit_code = "counterexample", 1
        elif any(case["lifetime_status"] == "inconclusive" for case in cases):
            report["status"], exit_code = "inconclusive", 2
        else:
            report["status"], exit_code = "demonstrated_on_synthetic_cases", 0
        report["stage"] = "complete"
    except Exception:
        exit_code = 1  # stage preserved; no exception strings, paths, source or AST content emitted
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError:
        print('{"status":"report_write_error"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
