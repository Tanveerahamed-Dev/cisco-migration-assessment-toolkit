"""Hosted-only order/cost diagnostic. No production gate or timing rule is replaced."""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

TARGET = "tests/test_vlan_carriage_budget.py::test_the_first_document_and_one_full_page_stay_within_their_api_budgets"
DIRECT_MODULES = (
    "tests/test_portable_desktop_proof.py", "tests/test_portable_maintenance.py",
    "tests/test_portable_maintenance_handoff.py", "tests/test_portable_managed_pe.py",
    "tests/test_portable_source_view.py", "tests/test_readme_field.py",
)
_PR_SOURCE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
_PR_TREE = "aa003b01248588220d22face7e8218f96a9ada84"
_DIRECT_NODE_COUNTS = (36, 132, 63, 86, 6, 35)  # Reconciled selected counts from run 39056614314 minus budget's 134.
COLLECTION_CASES = {
    "pr-full": (_PR_SOURCE, _PR_TREE, (), 20137),
    "main-full": ("b300a57b991746a9c284d513a365b330476480b4", "8242621d5e0650991ed4d0c50192b5421e43da87", (), 19784),
    "pr-without-six": (_PR_SOURCE, _PR_TREE, DIRECT_MODULES, 20137 - sum(_DIRECT_NODE_COUNTS)),
    **{"pr-without-" + Path(name).stem.removeprefix("test_"):
       (_PR_SOURCE, _PR_TREE, (name,), 20137 - count)
       for name, count in zip(DIRECT_MODULES, _DIRECT_NODE_COUNTS)},
}
_current_node = None
_gc_started = None
_duration_stream = None
_gc_stream = None
# Diagnostic-only references survive subject tests that replace shared module
# attributes. Product calls still see every original test patch and assertion.
_encode_report = json.dumps
_observed_clock = time.monotonic


def _gc_observer(phase, info):
    """Observe generation-2 cost/stack only; never collect or alter GC policy."""
    global _gc_started
    if info.get("generation") != 2 or _gc_stream is None:
        return
    if phase == "start":
        stack = []
        frame = sys._getframe(1)
        for _ in range(8):
            if frame is None:
                break
            stack.append((os.path.basename(frame.f_code.co_filename), frame.f_code.co_name, frame.f_lineno))
            frame = frame.f_back
        del frame
        _gc_started = (_observed_clock(), stack, _current_node)
    elif phase == "stop" and _gc_started is not None:
        started, stack, node = _gc_started
        _gc_started = None
        _gc_stream.write(_encode_report({"seconds": _observed_clock() - started, "stack": stack,
                                     "nodeid": node, "collected": info.get("collected"),
                                     "uncollectable": info.get("uncollectable")}) + "\n")


def pytest_configure(config):
    global _duration_stream, _gc_stream
    output = os.environ.get("ATLAS_ORDER_CASE")
    if output:
        # Open only external diagnostic reports before subject fixtures can
        # prohibit I/O. Never bypass or replace their product-side guards.
        _duration_stream = (Path(output) / "durations.jsonl").open("a", encoding="utf-8", buffering=1)
        _gc_stream = (Path(output) / "gc-generation2.jsonl").open("a", encoding="utf-8", buffering=1)
        gc.callbacks.append(_gc_observer)


def pytest_unconfigure(config):
    global _duration_stream, _gc_stream
    if _gc_observer in gc.callbacks:
        gc.callbacks.remove(_gc_observer)
    for stream in (_duration_stream, _gc_stream):
        if stream is not None:
            stream.close()
    _duration_stream = _gc_stream = None


def pytest_runtest_logstart(nodeid, location):
    global _current_node
    _current_node = nodeid


# Pytest plugin: select an explicitly disclosed prefix AFTER normal collection.
# It changes no fixture, assertion, validator, cache, GC policy or timed-leg rule.
def pytest_collection_modifyitems(config, items):
    output = os.environ.get("ATLAS_ORDER_CASE")
    if not output:
        return
    root = Path(output)
    (root / "collection.json").write_text(json.dumps([item.nodeid for item in items]), encoding="utf-8")
    selection = os.environ.get("ATLAS_ORDER_SELECTION")
    if selection:
        requested_nodes = json.loads(Path(selection).read_text(encoding="utf-8"))
        requested = set(requested_nodes)
        if len(requested) != len(requested_nodes):
            raise RuntimeError("diagnostic request contains duplicate node IDs")
        selected = [item for item in items if item.nodeid in requested]
        if len(selected) != len(requested) or {item.nodeid for item in selected} != requested:
            raise RuntimeError("diagnostic selection differs from collected node IDs")
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in requested])
        items[:] = selected
    (root / "selected.json").write_text(json.dumps([item.nodeid for item in items]), encoding="utf-8")


def pytest_runtest_logreport(report):
    if _duration_stream is not None:
        # Streaming records survive a job deadline; --durations=0 remains enabled too.
        _duration_stream.write(_encode_report({"nodeid": report.nodeid, "when": report.when,
                                         "seconds": report.duration, "outcome": report.outcome}) + "\n")


def pytest_runtest_setup(item):
    if item.nodeid == TARGET and os.environ.get("ATLAS_ORDER_CASE"):
        state = {"gc_enabled": gc.isenabled(), "gc_threshold": gc.get_threshold(),
                 "gc_counts": gc.get_count(), "gc_stats": gc.get_stats(),
                 "modules": len(sys.modules), "trace_present": sys.gettrace() is not None,
                 "observer_present": _gc_observer in gc.callbacks}
        (Path(os.environ["ATLAS_ORDER_CASE"]) / "before-budget.json").write_text(
            json.dumps(state, sort_keys=True), encoding="utf-8")


def changed_tests(subject: Path, baseline: str, source: str) -> list[str]:
    raw = subprocess.check_output(["git", "diff", "--name-only", baseline + "..." + source,
                                   "--", "tests", "webapp/tests"], cwd=subject, text=True)
    return [name for name in raw.splitlines() if name.endswith(".py") and Path(name).name.startswith("test_")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--mode", choices=("order", "cost", "plain", "minimal", "builtin", "direct", "collected", "collection-cut"), required=True)
    parser.add_argument("--cut-before", default="")
    parser.add_argument("--test-module", choices=("control", *DIRECT_MODULES), default="control")
    parser.add_argument("--collection-case", choices=tuple(COLLECTION_CASES), default="pr-full")
    args = parser.parse_args()
    subject, output = args.subject.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=subject, text=True).strip()
    if actual != args.source:
        raise RuntimeError("diagnostic checkout is not the selected exact source")
    # Workflow-start budget includes checkout/install time and reserves five
    # minutes inside the unchanged 120-minute job limit for final reporting.
    deadline = time.monotonic() + max(0, int(os.environ["ATLAS_DIAGNOSTIC_DEADLINE"]) - time.time())
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)}
    environment.pop("ATLAS_ORDER_CASE", None)
    environment.pop("ATLAS_ORDER_SELECTION", None)
    results = []

    def run(label, *, selection=None, paths=(), collect=False, plain=False, minimal=False):
        case = output / label
        case.mkdir()
        env = dict(os.environ) if plain else {**environment, "ATLAS_ORDER_CASE": str(case)}
        if plain:
            env.pop("ATLAS_ORDER_CASE", None)
            env.pop("ATLAS_ORDER_SELECTION", None)
        if minimal:
            env = {**environment, "ATLAS_MINIMAL_REPORT": str(case / "target-result.json"),
                   "ATLAS_MINIMAL_CUT_BEFORE": args.cut_before}
        if selection is not None:
            selected = case / "request.json"
            selected.write_text(json.dumps(selection), encoding="utf-8")
            env["ATLAS_ORDER_SELECTION"] = str(selected)
        command = ([sys.executable, "-m", "pytest", "--durations=40"] if plain else
                   [sys.executable, "-m", "pytest", "-p", "rc8_order_probe", "--durations=0"])
        if minimal:
            command = [sys.executable, "-m", "pytest", "-p", "rc8_minimal_prefix", "--durations=40"]
        if collect:
            command.append("--collect-only")
        command.extend(paths)
        if args.mode in ("direct", "collected", "collection-cut"):
            # Parent-only observations: no observer enters the timed process.
            # Names/PIDs only; never capture command arguments or environment secrets.
            (case / "processes-before.txt").write_text(subprocess.check_output(
                ["ps", "-eo", "pid,ppid,etimes,comm"], text=True), encoding="utf-8")
        started = time.monotonic()
        remaining = deadline - started
        if remaining <= 0:
            raise TimeoutError("diagnostic job budget exhausted before next prefix")
        with (case / "pytest.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=subject, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                code = 124
        if args.mode in ("direct", "collected", "collection-cut"):
            (case / "processes-after.txt").write_text(subprocess.check_output(
                ["ps", "-eo", "pid,ppid,etimes,comm"], text=True), encoding="utf-8")
        text = (case / "pytest.log").read_text(encoding="utf-8", errors="replace")
        measurements = []
        for line in text.splitlines():
            match = re.search(r"VLAN-CARRIAGE-BUDGET (\{.*\})", line)
            if match:
                value = json.loads(match[1])
                if value.get("kind") == "api":
                    measurements.append(value)
        target = []
        other_failures = []
        if (case / "durations.jsonl").exists():
            for line in (case / "durations.jsonl").read_text().splitlines():
                report = json.loads(line)
                if report["nodeid"] == TARGET and report["when"] == "call":
                    target.append(report)
                elif report["outcome"] == "failed":
                    other_failures.append(report)
        result = {"label": label, "source": actual, "command": command, "exit_code": code,
                  "wall_seconds": round(time.monotonic() - started, 3), "target": target,
                  "measurements": measurements, "other_failures": other_failures,
                  "selected_count": len(selection) if selection is not None else None}
        result["child_environment"] = {name: env.get(name) for name in (
            "GITHUB_ACTIONS", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTEST_ADDOPTS",
            "ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN", "ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE")}
        if plain:
            result["observation_scope"] = (
                ("Default collection minus declared collection exclusions, with built-in execution deselections. " if args.mode == "collection-cut" else
                 "Default collection with disclosed built-in whole-file execution deselections. " if args.mode == "collected" else
                 "Uninstrumented explicit module selection in one pytest process. " if args.mode == "direct" else
                 "Uninstrumented pytest with disclosed built-in collection exclusions. " if paths else
                 "Uninstrumented full default suite. ")
                + "No injected plugin or PYTHONPATH; "
                "no per-test reports. Read pytest.log for all failures and terminal summary."
            )
        if minimal:
            report_path = case / "target-result.json"
            minimal_report = json.loads(report_path.read_text()) if report_path.exists() else None
            result["minimal"] = minimal_report
            valid = False
            if minimal_report:
                nodes = minimal_report["collection"]
                modules = [node.split("::", 1)[0] for node in nodes]
                runs = [name for i, name in enumerate(modules) if i == 0 or name != modules[i - 1]]
                whole_files = len(runs) == len(set(runs))
                expected_failures = int(minimal_report["call"] == "failed")
                valid = bool(
                    code == minimal_report["pytest_exit"] == 2
                    and minimal_report["planned_stop"] and minimal_report["target_finishes"] == 1
                    and minimal_report["setup"] == minimal_report["teardown"] == "passed"
                    and minimal_report["call"] in ("passed", "failed")
                    and minimal_report["session_testsfailed"] == expected_failures
                    and nodes.count(TARGET) == 1 and whole_files
                    and ((not args.cut_before and minimal_report["omitted"] == 0)
                         or (bool(args.cut_before) and minimal_report["cut_seen"]
                             and minimal_report["omitted"] == nodes.index(TARGET) - modules.index(args.cut_before)
                             and nodes.index(TARGET) >= modules.index(args.cut_before)))
                    and len(measurements) == 1 and measurements[0]["timed"] is True
                )
            result["minimal_valid"] = valid
            result["first_page_budget_outcome"] = "invalid"
            if valid:
                first_ms = measurements[0]["first_page_ms"]
                if minimal_report["call"] == "passed" and first_ms <= 300:
                    result["first_page_budget_outcome"] = "within_budget"
                elif (minimal_report["call"] == "failed" and first_ms > 300
                      and re.search(r"assert\s+" + re.escape(str(first_ms)) + r"\s*<=\s*300\b",
                                    minimal_report["failure"] or "")):
                    result["first_page_budget_outcome"] = "over_budget"
                else:
                    result["first_page_budget_outcome"] = "other_failure"
            result["observation_scope"] = (
                "Minimal whole-file prefix; original collection/items/nextitem retained. "
                "Planned interrupted exit is not success. Requires a failing full-prefix control "
                "on this same observer before interpreting any reduction. No GC/per-test reporter."
            )
        results.append(result)
        (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("ORDER-DIAGNOSTIC " + json.dumps(result), flush=True)
        return result, case

    if args.mode in ("plain", "minimal", "builtin", "direct", "collected", "collection-cut"):
        provenance = {
            "source": actual,
            "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=subject, text=True).strip(),
            "python": sys.version,
            "pip_freeze": subprocess.check_output([sys.executable, "-m", "pip", "freeze"],
                                                   cwd=subject, text=True).splitlines(),
            "pytest_environment": {name: os.environ.get(name) for name in (
                "GITHUB_ACTIONS", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTEST_ADDOPTS",
                "ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN", "ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE")},
        }
        (output / "environment.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        if args.mode in ("direct", "collected", "collection-cut"):
            selected = [] if args.test_module == "control" else [args.test_module]
            budget_module = TARGET.split("::", 1)[0]
            paths = [*selected, budget_module]
            plan = {
                "source": actual, "tree": provenance["tree"], "case_module": args.test_module,
                "planned_execution_modules": paths, "same_pytest_process": True,
                "selection_mode": args.mode,
                "limits": "A slow case is a candidate; require the control and source-state evidence before attribution.",
                "process_observation_limit": "Before/after pytest only, not an in-process module-boundary observation.",
            }
            if args.mode in ("collected", "collection-cut"):
                order = json.loads((Path(__file__).parent / "rc8_default_order.json").read_text())
                ignored = ()
                expected_count = order["collection_count"]
                expected_source, expected_tree = order["source"], order["tree"]
                if args.mode == "collection-cut":
                    expected_source, expected_tree, ignored, expected_count = COLLECTION_CASES[args.collection_case]
                    if selected:
                        raise ValueError("collection-cut cases execute the complete budget module only")
                if actual != expected_source or provenance["tree"] != expected_tree or order["target"] != TARGET:
                    raise RuntimeError("default-collection navigation is not bound to this exact subject")
                if any(name not in order["prefix_modules"] for name in selected):
                    raise RuntimeError("selected module is not before the complete budget module in the order receipt")
                tracked = subprocess.check_output(
                    ["git", "ls-files", "--", "tests", "webapp/tests"], cwd=subject, text=True).splitlines()
                modules = [name for name in tracked if Path(name).name.startswith("test_") and name.endswith(".py")]
                if not set(paths) <= set(modules):
                    raise RuntimeError("requested execution module is not tracked under the default test paths")
                if not set(ignored) <= set(modules):
                    raise RuntimeError("requested collection exclusion is not tracked in this source")
                deselected = [name for name in modules if name not in paths and name not in ignored]
                plan.update({
                    "deselected_execution_modules": deselected,
                    "ignored_collection_modules": list(ignored),
                    "collection_case": args.collection_case if args.mode == "collection-cut" else None,
                    "expected_collection_count": expected_count,
                    "order_receipt_artifact": order["order_receipt_artifact"] if actual == order["source"] else None,
                    "count_receipt_artifact": 12099901646 if args.mode == "collection-cut" and args.collection_case == "main-full" else 12110325686,
                    "count_basis": "Prior observed full-collection count minus reconciled whole-module counts; fresh raw counts must confirm the expectation.",
                    "collection_limit": "Default collection minus declared ignores runs before built-in deselection. Counts are navigation expectations until raw reconciliation. Deselected items may be released; no per-node observer is injected. Ignores do not prove absence from transitive imports. Excluding all six whole modules is not main-equivalent; README tests also exist on main.",
                })
                # No explicit collection paths or injected hook. Collection-cut
                # cases disclose any whole-file ignores; otherwise keep the full
                # default collection. The :: node-prefix suffix is an exact file.
                paths = [*("--ignore=" + name for name in ignored),
                         *("--deselect=" + name + "::" for name in deselected)]
            (output / "direct-case.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
            label = ("collection-cut-budget" if args.mode == "collection-cut" else
                     "default-collected-module-then-budget" if args.mode == "collected" else "direct-module-then-budget")
            run(label, plain=True, paths=paths)
        elif args.mode == "builtin":
            order = json.loads((Path(__file__).parent / "rc8_default_order.json").read_text())
            if actual != order["source"] or provenance["tree"] != order["tree"] or order["target"] != TARGET:
                raise RuntimeError("built-in prefix navigation is not bound to this exact subject")
            modules = order["prefix_modules"]
            tracked_prefix = [name for name in subprocess.check_output(
                ["git", "ls-files", "--", "tests/test_*.py"], cwd=subject, text=True).splitlines()
                if name < TARGET.split("::", 1)[0]]
            if modules != tracked_prefix:
                raise RuntimeError("tracked module prefix differs from source-bound observed order")
            if args.cut_before and args.cut_before not in modules:
                raise ValueError("built-in prefix cut must name an observed whole file before TARGET")
            ignored = modules[modules.index(args.cut_before):] if args.cut_before else []
            (output / "builtin-prefix.json").write_text(json.dumps({
                "source": actual, "tree": provenance["tree"], "cut_before": args.cut_before,
                "ignored_collected_modules": ignored, "target_module_retained": TARGET.split("::", 1)[0],
                "later_modules_retained": True, "order_receipt_artifact": order["order_receipt_artifact"],
                "limits": "Collection AND execution reduction. Ignored files may still be imported by retained tests.",
            }, indent=2), encoding="utf-8")
            run("builtin-default-prefix", plain=True, paths=["--ignore=" + name for name in ignored])
        elif args.mode == "minimal":
            if args.cut_before and (not re.fullmatch(r"tests/test_[A-Za-z0-9_]+\.py", args.cut_before)
                                    or not (subject / args.cut_before).is_file()):
                raise ValueError("prefix cut must be one existing whole test file")
            run("minimal-default-prefix", minimal=True)
        else:
            run("plain-full-default-suite", plain=True)
        return 0  # retain the actual pytest exit in results, never an acceptance claim

    if args.mode == "cost":
        names = changed_tests(subject, args.baseline, "8c4b87d8bc149a30fcd05f5efcd123856a2778e6")
        present = [name for name in names if (subject / name).is_file()]
        (output / "cost-files.json").write_text(json.dumps({"changed": names, "present": present}), encoding="utf-8")
        run("changed-test-cost", paths=present)
        return 0  # diagnostic outcomes stay in the report, never become an acceptance receipt

    guard, _ = run("diagnostic-io-guard-control", paths=[
        "tests/test_ui_projection.py::test_t11_pure_no_file_socket_or_process_io",
        "tests/test_ui_projection_vlan_carriage.py::test_small_materialized_foreign_values_and_keys_keep_the_original_hook_order",
        "tests/test_ui_projection_vlan_carriage.py::test_small_materialized_replaced_stream_factory_keeps_original_calls_and_exact_bytes",
        "tests/test_research_http_guard.py::test_overall_deadline_is_enforced_during_slow_body_reads",
    ])
    if guard["exit_code"] != 0:
        raise RuntimeError("diagnostic writer did not survive the unchanged product I/O guard")
    _result, collected = run("collect-default", collect=True)
    order = json.loads((collected / "collection.json").read_text(encoding="utf-8"))
    all_modules = list(dict.fromkeys(node.split("::", 1)[0] for node in order))

    def collection_paths(modules):
        wanted = set(modules) | {TARGET.split("::", 1)[0]}
        return [name for name in all_modules if name in wanted]

    index = order.index(TARGET)
    prefix = order[:index]
    changed = set(changed_tests(subject, args.baseline, args.source))
    additions = [node for node in prefix if node.split("::", 1)[0] in changed]
    isolated, _ = run("isolated-budget", paths=[TARGET])
    empty, _ = run("all-collection-no-execution-prefix", selection=[TARGET])
    altered, _ = run("changed-execution-prefix", selection=[*additions, TARGET])

    def over_budget(result):
        return bool(result["exit_code"] == 1 and not result["other_failures"] and len(result["target"]) == 1
                    and result["target"][0]["outcome"] == "failed" and result["measurements"]
                    and result["measurements"][-1]["timed"] is True
                    and result["measurements"][-1]["first_page_ms"] > 300)

    def passed(result):
        return bool(result["exit_code"] == 0 and not result["other_failures"] and len(result["target"]) == 1
                    and result["target"][0]["outcome"] == "passed" and result["measurements"]
                    and result["measurements"][-1]["timed"] is True)

    if not passed(isolated):
        print("No isolated positive control; no causal polluter conclusion.", flush=True)
        return 0
    if not all(passed(result) or over_budget(result) for result in (empty, altered)):
        print("Collection/changed-prefix control was not a valid timed result; no causal conclusion.", flush=True)
        return 0
    collection = over_budget(empty)
    candidates = additions if over_budget(altered) else prefix
    if collection:
        candidates = list(dict.fromkeys(node.split("::", 1)[0] for node in order
                                        if node.split("::", 1)[0] != TARGET.split("::", 1)[0]))
        zero, _ = run("target-module-collection-control", selection=[TARGET], paths=collection_paths(()))
        if not passed(zero):
            print("Target module collection alone is not a positive control; no external polluter conclusion.", flush=True)
            return 0
    elif not over_budget(altered):
        full, _ = run("full-default-execution-prefix", selection=[*prefix, TARGET])
        if not over_budget(full):
            print("No polluted prefix reproduced; no causal polluter conclusion.", flush=True)
            return 0
    boundaries = candidates if collection else list(dict.fromkeys(node.split("::", 1)[0] for node in candidates))
    lower, upper = 0, len(boundaries)
    while upper - lower > 1:
        middle = (lower + upper) // 2
        if collection:
            result, _ = run(f"collection-prefix-{middle}", selection=[TARGET],
                            paths=collection_paths(boundaries[:middle]))
        else:
            modules = set(boundaries[:middle])
            selected = [node for node in candidates if node.split("::", 1)[0] in modules]
            result, _ = run(f"execution-prefix-{middle}", selection=[*selected, TARGET])
        if over_budget(result):
            upper = middle
        elif passed(result):
            lower = middle
        else:
            print("Prefix had a non-budget error; stopping without causal conclusion.", flush=True)
            return 0
    candidate = boundaries[upper - 1]
    (output / "candidate.json").write_text(json.dumps({"module": candidate, "collection": collection,
        "passing_prefix": lower, "failing_prefix": upper, "warning": "boundary candidate; independent causal controls still required"}), encoding="utf-8")
    print("BOUNDARY-CANDIDATE " + candidate, flush=True)
    if collection:
        run("candidate-collection-only", selection=[TARGET], paths=collection_paths([candidate]))
        run("all-collection-without-candidate", selection=[TARGET],
            paths=collection_paths([name for name in boundaries if name != candidate]))
    else:
        run("candidate-execution-only", selection=[*[node for node in prefix if node.split("::", 1)[0] == candidate], TARGET])
        run("execution-prefix-without-candidate", selection=[*[node for node in candidates
             if node.split("::", 1)[0] != candidate], TARGET])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
