"""Hosted-only round-6 paired investigation, never a replacement for normal CI.

One runner/interpreter/dependency resolution; isolated source worktrees and fresh
pytest processes. Keep failed observations, all original tests and their order.
"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


SUBJECTS = (
    ("baseline", "69bf8980167b86ad113b721d175213a67bcef803"),
    ("round5", "3abe9d0f435ddef23f2710e9e61088b722575ef3"),
)
FOCUSED = [
    "tests/test_vlan_carriage.py", "tests/test_ui_projection_vlan_carriage.py",
    "tests/test_vlan_carriage_budget.py", "tests/test_operator_evidence_contract.py",
    "tests/test_bound_snapshot_source.py", "webapp/tests/test_ui_projection_api.py",
    "webapp/tests/test_carriage_ingestion.py", "webapp/tests/test_snapshot_raw.py",
    "webapp/tests/test_carriage_lifecycle.py",
    "webapp/tests/test_atlas_unplug_safety.py::test_serve_main_legacy_preparation_limit_refuses_clearly_and_retries_original_snapshot",
]
TARGET = "tests/test_vlan_carriage_budget.py::test_the_stored_section_and_its_summary_stay_within_their_size_and_latency_budgets"


def _command(command, *, cwd, env=None):
    print("PAIR-COMMAND " + json.dumps(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _dependencies():
    """Bind installed distribution versions AND recorded installed-file digests."""
    records = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name == "cisco-migration-assessment-toolkit":
            continue  # Editable source intentionally follows each exact subject.
        record = distribution.read_text("RECORD") or ""
        records.append((name, distribution.version, hashlib.sha256(record.encode()).hexdigest()))
    return sorted(records)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15):
        raise SystemExit("This paired diagnostic requires hosted Linux Python 3.12.15")
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ["G14_PAIR_OUTPUT"]).resolve()
    subject = sys.argv[1]
    if subject not in {label for label, _ in SUBJECTS}:
        raise SystemExit("Expected baseline or round5")
    output.mkdir(parents=True, exist_ok=True)
    plugin_dir = output / "observer"
    plugin_dir.mkdir(exist_ok=True)
    shutil.copyfile(root / ".github/scripts/carriage_compute_observer.py", plugin_dir / "g14_compute_observer.py")
    dependencies = _dependencies()
    runtime = {
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
        "cpu": Path("/proc/cpuinfo").read_text(), "dependencies": dependencies,
        "observer_sha256": hashlib.sha256((plugin_dir / "g14_compute_observer.py").read_bytes()).hexdigest(),
        "execution_order": [f"{label}-{leg}" for label, _ in SUBJECTS for leg in ("focused", "complete")],
    }
    runtime_file = output / "runtime.json"
    if runtime_file.exists():
        previous = json.loads(runtime_file.read_text())
        for field in ("python", "executable", "platform", "image_os", "image_version", "observer_sha256"):
            if previous[field] != runtime[field]:
                raise RuntimeError("Shared runtime or observer identity changed")
        if previous["dependencies"] != [list(record) for record in dependencies]:
            raise RuntimeError("Dependency closure changed between paired steps")
    else:
        runtime_file.write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    results_path = output / "results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else []
    for label, source in SUBJECTS:
        if label != subject:
            continue
        checkout = Path(os.environ["RUNNER_TEMP"]) / f"g14-pair-source-{label}"
        _command(["git", "worktree", "add", "--detach", str(checkout), source], cwd=root)
        _command([sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."], cwd=checkout)
        if _dependencies() != dependencies:
            raise RuntimeError("Installed dependency closure changed between subjects")
        _command(["npm", "ci"], cwd=checkout / "atlas-scope")
        # Separate process; no target computation/prewarming. Catch editable-source aliasing.
        _command([sys.executable, "-c",
                  "from pathlib import Path; import cisco_toolkit, webapp; "
                  "assert Path(cisco_toolkit.__file__).resolve().parent.parent == Path.cwd(); "
                  "assert Path(webapp.__file__).resolve().parent.parent == Path.cwd()"], cwd=checkout)
        for leg, selection in (("focused", FOCUSED), ("complete", ["--durations=40"])):
            destination = output / f"{label}-{leg}"
            destination.mkdir()
            env = {
                **os.environ, "PYTHONPATH": str(plugin_dir), "PYTEST_PLUGINS": "g14_compute_observer",
                "G14_OBSERVER_OUTPUT": str(destination), "G14_OBSERVER_SOURCE": source,
                "G14_OBSERVER_LEG": leg,
            }
            command = [sys.executable, "-m", "pytest", *selection]
            print("PAIR-TEST " + json.dumps({"source": source, "leg": leg, "command": command}), flush=True)
            with (destination / "pytest.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=checkout, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end="", flush=True)
                code = process.wait()
            results.append({"source": source, "label": label, "leg": leg, "exit_code": code})
            results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            if _dependencies() != dependencies:
                raise RuntimeError("Installed dependency closure changed during a test process")
            # Continue to preserve the other side after any ORIGINAL assertion failure.
            # The combined job still fails below; no failure becomes a passing verdict.
    if subject == "baseline":
        return int(any(result["exit_code"] != 0 for result in results))
    observations = []
    for label, source in SUBJECTS:
        for leg in ("focused", "complete"):
            receipt = output / f"{label}-{leg}/observation.json"
            document = json.loads(receipt.read_text()) if receipt.exists() else {}
            measured = document.get("measurement", {})
            valid = (document.get("source") == source and document.get("leg") == leg
                     and document.get("observer_sha256") == runtime["observer_sha256"]
                     and "observer_error" not in measured
                     and all(type(measured.get(key)) in (int, float)
                             for key in ("original_timer_ms", "wall_ms", "process_cpu_ms")))
            observations.append({"label": label, "leg": leg, "valid": valid})
    (output / "observation-validation.json").write_text(json.dumps(observations, indent=2), encoding="utf-8")
    orders = {}
    for leg in ("focused", "complete"):
        sequences = [json.loads((output / f"{label}-{leg}/collection.json").read_text()) for label, _ in SUBJECTS]
        prefixes = [sequence[:sequence.index(TARGET) + 1] for sequence in sequences]
        common = set(sequences[0]) & set(sequences[1])
        relative = [[node for node in sequence if node in common] for sequence in sequences]
        orders[leg] = {
            "collected_counts": [len(sequence) for sequence in sequences],
            "through_compute_count": len(prefixes[0]), "through_compute_identical": prefixes[0] == prefixes[1],
            "through_compute_sha256": [hashlib.sha256(json.dumps(prefix).encode()).hexdigest() for prefix in prefixes],
            "common_relative_order_identical": relative[0] == relative[1],
            "only_baseline": [node for node in sequences[0] if node not in common],
            "only_round5": [node for node in sequences[1] if node not in common],
        }
    (output / "order-comparison.json").write_text(json.dumps(orders, indent=2), encoding="utf-8")
    print("PAIR-RESULT " + json.dumps({"executions": results, "orders": orders}), flush=True)
    return int(any(result["exit_code"] != 0 for result in results)
               or not all(observation["valid"] for observation in observations)
               or not all(order["through_compute_identical"] and order["common_relative_order_identical"]
                          for order in orders.values()))


if __name__ == "__main__":
    raise SystemExit(main())
