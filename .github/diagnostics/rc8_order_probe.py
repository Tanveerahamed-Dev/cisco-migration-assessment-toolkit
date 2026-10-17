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
_current_node = None
_gc_started = None


def _gc_observer(phase, info):
    """Observe generation-2 cost/stack only; never collect or alter GC policy."""
    global _gc_started
    if info.get("generation") != 2 or not os.environ.get("ATLAS_ORDER_CASE"):
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
        _gc_started = (time.monotonic(), stack, _current_node)
    elif phase == "stop" and _gc_started is not None:
        started, stack, node = _gc_started
        _gc_started = None
        with (Path(os.environ["ATLAS_ORDER_CASE"]) / "gc-generation2.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"seconds": time.monotonic() - started, "stack": stack,
                                     "nodeid": node, "collected": info.get("collected"),
                                     "uncollectable": info.get("uncollectable")}) + "\n")


def pytest_configure(config):
    if os.environ.get("ATLAS_ORDER_CASE"):
        gc.callbacks.append(_gc_observer)


def pytest_unconfigure(config):
    if _gc_observer in gc.callbacks:
        gc.callbacks.remove(_gc_observer)


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
    output = os.environ.get("ATLAS_ORDER_CASE")
    if output:
        # Streaming records survive a job deadline; --durations=0 remains enabled too.
        with (Path(output) / "durations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"nodeid": report.nodeid, "when": report.when,
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
    parser.add_argument("--mode", choices=("order", "cost"), required=True)
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

    def run(label, *, selection=None, paths=(), collect=False):
        case = output / label
        case.mkdir()
        env = {**environment, "ATLAS_ORDER_CASE": str(case)}
        if selection is not None:
            selected = case / "request.json"
            selected.write_text(json.dumps(selection), encoding="utf-8")
            env["ATLAS_ORDER_SELECTION"] = str(selected)
        command = [sys.executable, "-m", "pytest", "-p", "rc8_order_probe", "--durations=0"]
        if collect:
            command.append("--collect-only")
        command.extend(paths)
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
        results.append(result)
        (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("ORDER-DIAGNOSTIC " + json.dumps(result), flush=True)
        return result, case

    if args.mode == "cost":
        names = changed_tests(subject, args.baseline, "8c4b87d8bc149a30fcd05f5efcd123856a2778e6")
        present = [name for name in names if (subject / name).is_file()]
        (output / "cost-files.json").write_text(json.dumps({"changed": names, "present": present}), encoding="utf-8")
        run("changed-test-cost", paths=present)
        return 0  # diagnostic outcomes stay in the report, never become an acceptance receipt

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
