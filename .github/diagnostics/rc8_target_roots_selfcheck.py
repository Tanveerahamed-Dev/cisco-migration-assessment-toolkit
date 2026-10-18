"""Standalone hosted-only checks of the TARGET observer on synthetic objects.

Never imported into the product pytest process. No project module is imported,
no GC collection/policy is requested, and no source or fixture is modified.
"""

import argparse
import ast
import importlib.util
import os
from pathlib import Path
import sys
import types


def _operator_like():
    owner = {}

    def visit(node):
        for child in ast.iter_child_nodes(node):
            owner[child] = "RC8-PRIVATE-VALUE-CANARY"
            visit(child)

    visit(ast.parse("def example(value=1):\n    return value\n"))
    return visit, owner


def _host(plugin):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15)
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host refused")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
               for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
        raise ValueError("host refused")
    expected = Path(__file__).resolve(strict=True).with_name("rc8_target_roots.py")
    if plugin.is_symlink() or plugin.resolve(strict=True) != expected:
        raise ValueError("plugin refused")
    spec = importlib.util.spec_from_file_location("_rc8_target_roots_selfcheck_subject", expected)
    if spec is None or spec.loader is None:
        raise ValueError("loader refused")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checks(plugin):
    class PoisonMeta(type):
        def __hash__(cls):
            raise AssertionError("foreign metaclass hash")

        def __eq__(cls, other):
            raise AssertionError("foreign metaclass equality")

    class Poison(metaclass=PoisonMeta):
        def __getattribute__(self, name):
            raise AssertionError("foreign attribute")

        def __sizeof__(self):
            raise AssertionError("foreign sizeof")

        def __repr__(self):
            raise AssertionError("foreign repr")

        def __str__(self):
            raise AssertionError("foreign str")

        def __iter__(self):
            raise AssertionError("foreign iterator")

    function, owner = _operator_like()
    shared, cycle = [], []
    cycle.append(cycle)
    owner.update({"RC8-PRIVATE-KEY-CANARY": shared, "alias": shared, "cycle": cycle, "poison": Poison()})
    code = function.__code__
    binding = {"operator_enclosing_visit": {
        "filename": code.co_filename, "line": code.co_firstlineno,
        "qualname": code.co_qualname, "freevars": ("owner", "visit"),
        "relative": "tests/synthetic_operator.py", "root_name": "owner", "root_type": dict,
    }}
    # The target is beyond the previous 1M-object analysis boundary. Repeated
    # None entries are a synthetic positional check, not a real heap snapshot.
    snapshot = [None] * 1_000_001 + [Poison(), function]
    summary, roots = plugin._summarize(snapshot, binding, {})
    assert summary["census_complete_for_snapshot"]
    assert summary["inspected"] == len(snapshot) and summary["uninspected_tail"] == 0
    assert sum(summary["type_counts"].values()) == len(snapshot)
    site = summary["targeted_sites"]["operator_enclosing_visit"]
    assert site["matched_functions"] == 1 and site["unique_roots"] == 1
    assert site["slots"] == {"owner": {"dict": 1}, "visit": {"function": 1}}
    assert roots["operator_enclosing_visit"][0] is owner
    graph = plugin._walk(roots["operator_enclosing_visit"], {})
    assert graph["types"]["ast.FunctionDef"]["count"] == 1
    assert graph["unknown_edges"] == 1 and graph["coverage"] == "partial"
    assert not graph["traversal_capped"]

    prefix, omitted_roots = plugin._summarize(snapshot, binding, {}, max_objects=1_000_000)
    assert not prefix["census_complete_for_snapshot"]
    assert prefix["uninspected_tail"] == len(snapshot) - 1_000_000
    assert prefix["targeted_sites"]["operator_enclosing_visit"]["matched_functions"] == 0
    capped, capped_roots = plugin._summarize(snapshot, binding, {}, max_roots=0)
    assert capped["targeted_sites"]["operator_enclosing_visit"]["roots_omitted_by_cap"] == 1
    assert not capped_roots["operator_enclosing_visit"]

    wrong = {"operator_enclosing_visit": dict(binding["operator_enclosing_visit"], freevars=("wrong",))}
    mismatch, rejected = plugin._summarize([function], wrong, {})
    assert mismatch["target_code_binding_mismatches"] == 1
    assert not mismatch["target_search_complete_for_inspected_functions"]
    assert not rejected["operator_enclosing_visit"]

    class PoisonStr(str):
        def __eq__(self, other):
            raise AssertionError("foreign code metadata equality")

        def __str__(self):
            raise AssertionError("foreign code metadata str")

        def __repr__(self):
            raise AssertionError("foreign code metadata repr")

    # CPython may refuse or normalize subclasses during CodeType.replace.
    # Only a preserved subclass exercises the observer's refusal branch.
    metadata_checks = {}
    for field in ("co_filename", "co_name", "co_qualname", "co_freevars"):
        requested = (tuple(PoisonStr(name) for name in code.co_freevars) if field == "co_freevars"
                     else PoisonStr("RC8-PRIVATE-CODE-METADATA-CANARY"))
        try:
            changed = code.replace(**{field: requested})
        except (TypeError, ValueError):
            metadata_checks[field] = "constructor_refused"
            continue
        actual = getattr(changed, field)  # fixed whitelist on an exact builtin CodeType
        retained = (any(type(name) is PoisonStr for name in actual) if field == "co_freevars"
                    else type(actual) is PoisonStr)
        clone = types.FunctionType(changed, globals(), closure=function.__closure__)
        if retained:
            unsafe, unsafe_roots = plugin._summarize([clone], binding, {})
            assert unsafe["census_complete_for_snapshot"]
            assert unsafe["unsafe_code_metadata_count"] == 1
            assert not unsafe["target_search_complete_for_inspected_functions"]
            assert unsafe["targeted_sites"]["operator_enclosing_visit"]["matched_functions"] == 0
            assert not unsafe_roots["operator_enclosing_visit"]
            assert "RC8-PRIVATE-CODE-METADATA-CANARY" not in plugin._ENCODE(unsafe)
            metadata_checks[field] = "preserved_and_observer_refused"
        else:
            assert plugin._site(clone, binding) != "unsafe_code_metadata"
            metadata_checks[field] = "constructor_normalized"
    assert plugin._walk([cycle], {})["unique_visits"] == 1
    assert plugin._walk([[shared, shared]], {})["types"]["list"]["count"] == 2
    assert plugin._walk([list(range(10))], {}, visits=2)["traversal_capped"]
    assert plugin._walk([cycle], {}, edges=1)["traversal_capped"]
    assert plugin._walk([[[[]]]], {}, depth=2)["traversal_capped"]

    encoded = plugin._ENCODE({"summary": summary, "graph": graph, "prefix": prefix,
                              "capped": capped, "mismatch": mismatch})
    assert "RC8-PRIVATE-VALUE-CANARY" not in encoded and "RC8-PRIVATE-KEY-CANARY" not in encoded
    assert "Poison" not in encoded and code.co_filename not in encoded
    assert plugin.LIMITS["instrumented_timings_are_not_acceptance"]
    assert plugin.LIMITS["type_census_is_not_complete_heap_ownership"]
    assert plugin.LIMITS["source_position_matches_do_not_prove_runtime_code_or_ownership"]
    for group in (roots, omitted_roots, capped_roots, rejected):
        for values in group.values():
            values.clear()
        group.clear()
    snapshot.clear()
    cycle.clear()
    owner.clear()
    return metadata_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        metadata_checks = _checks(_host(arguments.plugin))
    except Exception:
        print('{"self_check":"refused_or_failed"}')
        return 1
    print('{"self_check":"passed","synthetic_target_beyond_old_1m_boundary":true}')
    # These fixed field/branch labels contain no code metadata values.
    import json
    print(json.dumps({"code_metadata_subclass_checks": metadata_checks}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
