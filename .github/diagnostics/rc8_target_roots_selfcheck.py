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

_TYPE = type
_TELEMETRY = {"stage": "arguments", "check": "none"}
_EXCEPTION_CATEGORIES = (
    (AssertionError, "AssertionError"), (KeyError, "KeyError"), (TypeError, "TypeError"),
    (ValueError, "ValueError"), (AttributeError, "AttributeError"),
    (ImportError, "ImportError"), (ModuleNotFoundError, "ModuleNotFoundError"),
    (OSError, "OSError"), (FileNotFoundError, "FileNotFoundError"),
    (PermissionError, "PermissionError"), (RuntimeError, "RuntimeError"),
    (MemoryError, "MemoryError"), (RecursionError, "RecursionError"), (SystemError, "SystemError"),
)


def _at(stage, check="none"):
    # Every caller supplies literal labels, or a field from the literal four-field loop.
    _TELEMETRY["stage"], _TELEMETRY["check"] = stage, check


def _exception_category(error):
    kind = _TYPE(error)
    for exact, label in _EXCEPTION_CATEGORIES:
        if kind is exact:
            return label
    return "unlisted"


def _operator_like():
    owner = {}

    def visit(node):
        for child in ast.iter_child_nodes(node):
            owner[child] = "RC8-PRIVATE-VALUE-CANARY"
            visit(child)

    visit(ast.parse("def example(value=1):\n    return value\n"))
    return visit, owner


def _host(plugin):
    _at("host_guard")
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15)
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host refused")
    _at("os_release_guard")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
               for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
        raise ValueError("host refused")
    _at("plugin_path_guard")
    expected = Path(__file__).resolve(strict=True).with_name("rc8_target_roots.py")
    if plugin.is_symlink() or plugin.resolve(strict=True) != expected:
        raise ValueError("plugin refused")
    _at("plugin_import")
    spec = importlib.util.spec_from_file_location("_rc8_target_roots_selfcheck_subject", expected)
    if spec is None or spec.loader is None:
        raise ValueError("loader refused")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checks(plugin):
    _at("positive_fixture")
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
    _at("positive_census")
    summary, roots = plugin._summarize(snapshot, binding, {})
    _at("positive_assertion", "complete")
    assert summary["census_complete_for_snapshot"]
    _at("positive_assertion", "tail")
    assert summary["inspected"] == len(snapshot) and summary["uninspected_tail"] == 0
    _at("positive_assertion", "type_counts")
    assert sum(summary["type_counts"].values()) == len(snapshot)
    site = summary["targeted_sites"]["operator_enclosing_visit"]
    _at("positive_assertion", "function_and_root_counts")
    assert site["matched_functions"] == 1 and site["unique_roots"] == 1
    _at("positive_assertion", "slots")
    assert site["slots"] == {"owner": {"dict": 1}, "visit": {"function": 1}}
    _at("positive_assertion", "root_identity")
    assert roots["operator_enclosing_visit"][0] is owner
    _at("root_graph")
    graph = plugin._walk(roots["operator_enclosing_visit"], {})
    _at("graph_assertion", "ast_function")
    assert graph["types"]["ast.FunctionDef"]["count"] == 1
    _at("graph_assertion", "unknown_and_partial")
    assert graph["unknown_edges"] == 1 and graph["coverage"] == "partial"
    _at("graph_assertion", "uncapped")
    assert not graph["traversal_capped"]

    _at("prefix_census")
    prefix, omitted_roots = plugin._summarize(snapshot, binding, {}, max_objects=1_000_000)
    _at("prefix_assertion", "incomplete")
    assert not prefix["census_complete_for_snapshot"]
    _at("prefix_assertion", "tail")
    assert prefix["uninspected_tail"] == len(snapshot) - 1_000_000
    _at("prefix_assertion", "target_outside_prefix")
    assert prefix["targeted_sites"]["operator_enclosing_visit"]["matched_functions"] == 0
    _at("root_cap_census")
    capped, capped_roots = plugin._summarize(snapshot, binding, {}, max_roots=0)
    _at("root_cap_assertion", "omitted_root")
    assert capped["targeted_sites"]["operator_enclosing_visit"]["roots_omitted_by_cap"] == 1
    _at("root_cap_assertion", "no_retained_root")
    assert not capped_roots["operator_enclosing_visit"]

    _at("mismatch_census")
    wrong = {"operator_enclosing_visit": dict(binding["operator_enclosing_visit"], freevars=("wrong",))}
    mismatch, rejected = plugin._summarize([function], wrong, {})
    _at("mismatch_assertion", "count")
    assert mismatch["target_code_binding_mismatches"] == 1
    _at("mismatch_assertion", "incomplete_search")
    assert not mismatch["target_search_complete_for_inspected_functions"]
    _at("mismatch_assertion", "no_retained_root")
    assert not rejected["operator_enclosing_visit"]

    _at("metadata_poison_class")
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
    original_freevars = code.co_freevars
    original_closure = function.__closure__
    original_cells = tuple(cell for cell in original_closure)
    original_contents = tuple(cell.cell_contents for cell in original_closure)
    for field in ("co_filename", "co_name", "co_qualname", "co_freevars"):
        _at("metadata_constructor", field)
        requested = (tuple(PoisonStr(name) for name in code.co_freevars) if field == "co_freevars"
                     else PoisonStr("RC8-PRIVATE-CODE-METADATA-CANARY"))
        try:
            changed = code.replace(**{field: requested})
        except (TypeError, ValueError):
            metadata_checks[field] = "constructor_refused"
            continue
        except SystemError as error:
            # CPython 3.12.15 code_replace_impl forwards this supplied tuple
            # to intern_strings via localsplusnames. That helper rejects
            # non-exact Unicode with SystemError. No other SystemError is admitted.
            # https://github.com/python/cpython/blob/e848e4b09ca4bc67c0041c9ce7526dae471d4c36/Objects/codeobject.c
            if (_TYPE(error) is not SystemError or field != "co_freevars"
                    or _TYPE(requested) is not tuple or len(requested) != len(original_freevars)
                    or any(_TYPE(name) is not PoisonStr for name in requested)):
                raise
            _at("metadata_refusal_invariants", "original_code")
            assert function.__code__ is code
            _at("metadata_refusal_invariants", "original_freevars_types")
            assert _TYPE(code.co_freevars) is tuple and all(_TYPE(name) is str for name in code.co_freevars)
            _at("metadata_refusal_invariants", "original_freevars_values")
            assert code.co_freevars == original_freevars
            _at("metadata_refusal_invariants", "original_freevar_identities")
            assert all(current is original for current, original in zip(code.co_freevars, original_freevars))
            _at("metadata_refusal_invariants", "original_closure_tuple")
            assert function.__closure__ is original_closure
            _at("metadata_refusal_invariants", "original_cell_identities")
            assert all(current is original for current, original in zip(function.__closure__, original_cells))
            _at("metadata_refusal_invariants", "original_content_identities")
            assert all(cell.cell_contents is content for cell, content in zip(original_closure, original_contents))
            metadata_checks[field] = "constructor_refused_exact_systemerror"
            continue
        _at("metadata_classification", field)
        actual = getattr(changed, field)  # fixed whitelist on an exact builtin CodeType
        retained = (any(type(name) is PoisonStr for name in actual) if field == "co_freevars"
                    else type(actual) is PoisonStr)
        _at("metadata_function_constructor", field)
        clone = types.FunctionType(changed, globals(), closure=function.__closure__)
        if retained:
            _at("metadata_observe", field)
            unsafe, unsafe_roots = plugin._summarize([clone], binding, {})
            _at("metadata_assert_complete", field)
            assert unsafe["census_complete_for_snapshot"]
            _at("metadata_assert_unsafe_count", field)
            assert unsafe["unsafe_code_metadata_count"] == 1
            _at("metadata_assert_incomplete_search", field)
            assert not unsafe["target_search_complete_for_inspected_functions"]
            _at("metadata_assert_no_target", field)
            assert unsafe["targeted_sites"]["operator_enclosing_visit"]["matched_functions"] == 0
            _at("metadata_assert_no_retained_root", field)
            assert not unsafe_roots["operator_enclosing_visit"]
            _at("metadata_assert_private_canary", field)
            assert "RC8-PRIVATE-CODE-METADATA-CANARY" not in plugin._ENCODE(unsafe)
            metadata_checks[field] = "preserved_and_observer_refused"
        else:
            _at("metadata_normalized_observe", field)
            assert plugin._site(clone, binding) != "unsafe_code_metadata"
            metadata_checks[field] = "constructor_normalized"
    _at("healthy_exact_string_constructor")
    healthy_code = code.replace(co_freevars=original_freevars)
    healthy_function = types.FunctionType(healthy_code, globals(), closure=original_closure)
    _at("healthy_constructor_assertion", "code_type")
    assert _TYPE(healthy_code) is types.CodeType
    _at("healthy_constructor_assertion", "exact_freevars")
    assert _TYPE(healthy_code.co_freevars) is tuple and all(_TYPE(name) is str for name in healthy_code.co_freevars)
    _at("healthy_constructor_assertion", "unchanged_freevars")
    assert healthy_code.co_freevars == original_freevars
    _at("healthy_constructor_assertion", "unchanged_bytecode")
    assert healthy_code.co_code == code.co_code
    _at("healthy_constructor_assertion", "copied_target_site")
    assert plugin._site(healthy_function, binding) == "operator_enclosing_visit"
    _at("healthy_constructor_assertion", "original_target_site")
    assert plugin._site(function, binding) == "operator_enclosing_visit"
    _at("cycle_assertion")
    assert plugin._walk([cycle], {})["unique_visits"] == 1
    _at("alias_assertion")
    assert plugin._walk([[shared, shared]], {})["types"]["list"]["count"] == 2
    _at("visit_cap_assertion")
    assert plugin._walk([list(range(10))], {}, visits=2)["traversal_capped"]
    _at("edge_cap_assertion")
    assert plugin._walk([cycle], {}, edges=1)["traversal_capped"]
    _at("depth_cap_assertion")
    assert plugin._walk([[[[]]]], {}, depth=2)["traversal_capped"]

    _at("privacy_encoding")
    encoded = plugin._ENCODE({"summary": summary, "graph": graph, "prefix": prefix,
                              "capped": capped, "mismatch": mismatch})
    _at("privacy_assertion", "key_and_value")
    assert "RC8-PRIVATE-VALUE-CANARY" not in encoded and "RC8-PRIVATE-KEY-CANARY" not in encoded
    _at("privacy_assertion", "foreign_name_and_path")
    assert "Poison" not in encoded and code.co_filename not in encoded
    _at("limits_assertion", "timing")
    assert plugin.LIMITS["instrumented_timings_are_not_acceptance"]
    _at("limits_assertion", "ownership")
    assert plugin.LIMITS["type_census_is_not_complete_heap_ownership"]
    _at("limits_assertion", "source_position")
    assert plugin.LIMITS["source_position_matches_do_not_prove_runtime_code_or_ownership"]
    _at("cleanup")
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
    except Exception as error:
        import json
        print(json.dumps({"self_check": "refused_or_failed", **_TELEMETRY,
                          "exception_category": _exception_category(error)}, sort_keys=True))
        return 1
    print('{"self_check":"passed","synthetic_target_beyond_old_1m_boundary":true}')
    # These fixed field/branch labels contain no code metadata values.
    import json
    print(json.dumps({"code_metadata_subclass_checks": metadata_checks}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
