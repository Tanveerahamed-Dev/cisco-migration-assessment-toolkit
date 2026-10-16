"""Hosted-only frozen desktop proof with Python hidden from every Atlas child.

The absolute build interpreter drives observations; no Python interpreter, launcher,
repository working directory or Python environment is provided to the application.
This simulated absence does not replace qualification on an actual disconnected host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PYTHON_COMMANDS = ("python.exe", "python3.exe", "pythonw.exe", "py.exe", "pip.exe", "pip3.exe")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def published_digest(package: Path) -> str:
    rows = package.with_suffix(".SHA256SUMS").read_text(encoding="ascii").splitlines()
    selected = [row.split("  ", 1)[0] for row in rows if row.endswith("  " + package.name)]
    require(len(selected) == 1 and len(selected[0]) == 64
            and all(char in "0123456789abcdef" for char in selected[0]),
            "published checksums do not bind exactly one ZIP digest")
    require(digest(package) == selected[0], "release ZIP differs from published SHA-256")
    return selected[0]


def runtime_environment(inherited: dict[str, str], scratch: Path) -> dict[str, str]:
    removed = {"path", "pythonhome", "pythonpath", "virtual_env", "conda_prefix",
               "http_proxy", "https_proxy", "all_proxy", "atlas_portable_allow_live_network",
               "assesshub_db", "assesshub_instance_nonce", "assesshub_native_validation_smoke"}
    environment = {key: value for key, value in inherited.items() if key.casefold() not in removed}
    system_root = next((value for key, value in inherited.items() if key.casefold() == "systemroot"), r"C:\Windows")
    environment["PATH"] = str(Path(system_root) / "System32")
    environment["TEMP"] = environment["TMP"] = str(scratch / "Temp")
    environment["USERPROFILE"] = str(scratch)
    environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
    Path(environment["TEMP"]).mkdir(parents=True, exist_ok=True)
    return environment


def assert_python_hidden(environment: dict[str, str], cwd: Path) -> None:
    where = Path(environment["PATH"]) / "where.exe"
    require(where.is_file(), "Windows executable-lookup probe is absent")
    for command in PYTHON_COMMANDS:
        result = subprocess.run([str(where), command], cwd=cwd, env=environment,
                                capture_output=True, timeout=20, check=False)
        require(result.returncode == 1, f"Python-absent lookup failed for {command}")
    require(not {key.casefold() for key in environment} & {"pythonhome", "pythonpath"},
            "Python runtime overrides survived sanitization")


def run(executable: Path, arguments: list[str], environment: dict[str, str], cwd: Path,
        *, timeout: int = 300) -> subprocess.CompletedProcess:
    result = subprocess.run([str(executable), *arguments], cwd=cwd, env=environment,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    require(result.returncode == 0,
            f"frozen {arguments[0]} failed ({result.returncode}): {result.stderr[-1600:]}")
    return result


def validate_result(value: object, expected_code: int) -> dict:
    require(isinstance(value, dict), "maintenance result is not an object")
    require(value.get("schema") == "atlas.maintenance-result/1", "unknown maintenance result schema")
    require(type(value.get("exit_code")) is int and value["exit_code"] == expected_code,
            "maintenance worker failed or reported an unexpected exit code")
    require(value.get("status") == ("complete" if expected_code == 0 else "refused"),
            "maintenance status contradicts its worker exit code")
    require(value.get("verifier_origin") == "installed_atlas", "update did not use installed verifier")
    require(value.get("verification_policy") == "sha256_bound_runtime_extension",
            "maintenance verifier policy differs")
    return value


def maintenance(executable: Path, arguments: list[str], environment: dict[str, str],
                cwd: Path, *, expected_code: int = 0) -> dict:
    receipt = cwd / ("Atlas.maintenance-result." + secrets.token_hex(16) + ".json")
    # Dispatch exit zero is insufficient: the application must publish a terminal
    # worker receipt after its Windows handles have been released and the switch ends.
    run(executable, [*arguments, "--maintenance-result", str(receipt)], environment, cwd)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if receipt.is_file():
            return validate_result(json.loads(receipt.read_text(encoding="utf-8")), expected_code)
        time.sleep(0.25)
    raise RuntimeError("maintenance worker did not publish its terminal result within 300 seconds")


def files(root: Path, *, exclude_data: bool = False) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if exclude_data and relative.split("/", 1)[0].casefold() == "data":
            continue
        require(not path.is_symlink() and not getattr(path.lstat(), "st_file_attributes", 0) & 0x400,
                "proof tree contains a redirected entry")
        if path.is_file():
            result[relative] = digest(path)
    return result


def tree_digest(root: Path) -> str:
    rows = [f"{name}\0{root.joinpath(*name.split('/')).stat().st_size}\0{sha}"
            for name, sha in files(root, exclude_data=True).items()]
    # Mirrors the transaction's Ordinal UTF-16 sort, including non-ASCII names.
    rows.sort(key=lambda value: value.encode("utf-16-be"))
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def database_state(path: Path) -> dict:
    require(path.is_file(), "installed application did not create its real database")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        require(connection.execute("PRAGMA quick_check").fetchall() == [("ok",)],
                "installed database failed quick_check")
        rows = connection.execute("SELECT id, campaign_id, label, snapshot_json FROM snapshots ORDER BY id").fetchall()
    require(bool(rows), "real database has no demo snapshot rows")
    return {"sha256": digest(path), "rows": rows}


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def seed_database(executable: Path, environment: dict[str, str], cwd: Path) -> None:
    nonce = secrets.token_urlsafe(24)
    child_environment = {**environment, "ASSESSHUB_INSTANCE_NONCE": nonce}
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile(mode="w+b") as log:
        server = subprocess.Popen([str(executable), "--no-browser", "--port", str(port)],
                                  env=child_environment, cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                require(server.poll() is None, "installed database seed server exited early")
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=3) as response:
                        health = json.load(response)
                    if health.get("instance_nonce") == nonce and server.poll() is None:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("seed server failed its process-bound health check")
            request = urllib.request.Request(base + "/api/demo/seed", data=b"",
                                             headers={"Origin": base, "Sec-Fetch-Site": "same-origin"})
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.load(response)
                require(response.status == 200 and type(value["snapshot"]["id"]) is int
                        and value["snapshot"]["id"] > 0 and server.poll() is None,
                        "real application did not seed its synthetic demo")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


def unchanged_data(before: dict[str, str], data: Path) -> None:
    after = files(data)
    require(all(after.get(name) == sha for name, sha in before.items()),
            "maintenance changed or removed existing client data")


def verify_slot(destination: Path) -> None:
    active, previous = destination / "Atlas", destination / "Atlas.previous"
    require(previous.is_dir() and not (previous / "data").exists(),
            "rollback slot is missing or carries client data")
    value = json.loads((destination / "Atlas.rollback-slot.json").read_text(encoding="utf-8"))
    require(value.get("schema") == "atlas.portable-rollback-slot/1", "rollback slot schema differs")
    for prefix, directory in (("active", active), ("previous", previous)):
        require(value.get(prefix + "_exe_sha256") == digest(directory / "Atlas.exe"),
                "rollback slot executable digest differs")
        require(value.get(prefix + "_tree_sha256") == tree_digest(directory),
                "rollback slot whole-application digest differs")
    require(not (destination / "Atlas.update-state.json").exists(), "completed update retained a journal")


def recovery_helper(destination: Path) -> Path:
    pointer = json.loads((destination / "Atlas.maintenance.json").read_text(encoding="utf-8"))
    relative = pointer.get("helper")
    require(pointer.get("schema") == "atlas.maintenance-recovery/1" and isinstance(relative, str)
            and re.fullmatch(r"Atlas\.maintenance-[0-9a-f]{32}/Atlas/Atlas\.exe", relative) is not None,
            "interrupted maintenance did not retain a safe installed-code recovery pointer")
    helper = destination.joinpath(*relative.split("/"))
    require(helper.resolve(strict=True).is_relative_to(destination.resolve(strict=True)),
            "recovery helper escapes the installation destination")
    require(digest(helper) == pointer.get("helper_exe_sha256"), "recovery helper executable digest differs")
    return helper


def extract_bootstrap(package: Path, destination: Path) -> Path:
    with zipfile.ZipFile(package) as archive:
        for entry in archive.infolist():
            parts = entry.filename.replace("\\", "/").split("/")
            require(parts[0] == "Atlas" and not any(part in {".", ".."} or ":" in part for part in parts),
                    "bootstrap ZIP member escapes its Atlas directory")
        archive.extractall(destination)
    executable = destination / "Atlas" / "Atlas.exe"
    require(executable.is_file(), "release ZIP contains no frozen executable")
    return executable


def prove(release_directory: Path, *, baseline_package: Path | None = None) -> dict:
    require(os.name == "nt", "Python-absent desktop proof requires hosted Windows")
    packages = list(release_directory.glob("Atlas-*-windows-x64.zip"))
    require(len(packages) == 1, "proof requires exactly one packaged release ZIP")
    package, = packages
    expected_sha = published_digest(package)
    baseline_package = package if baseline_package is None else baseline_package.resolve(strict=True)
    baseline_sha = published_digest(baseline_package)
    # The package was already verified by the producer's strict closed-set check.
    # The first-install caller explicitly binds the exact published ZIP digest.
    with tempfile.TemporaryDirectory(prefix="atlas-desktop-no-python-") as temporary:
        scratch = Path(temporary).resolve()
        require(scratch != ROOT and ROOT not in scratch.parents, "proof working directory is inside the repo")
        environment = runtime_environment(dict(os.environ), scratch / "profile")
        assert_python_hidden(environment, scratch)
        bootstrap = extract_bootstrap(package, scratch / "bootstrap")
        sys.path.insert(0, str(ROOT))
        from portable.build_atlas import selftest_gap, smoke

        # Reuse the canonical four-step smoke without changing its assertions/output.
        smoke(unused_port(), dist=bootstrap.parent, environment=environment)
        standalone = run(bootstrap, ["--selftest", "--db", str(scratch / "bootstrap-check.db")],
                         environment, scratch, timeout=180)
        require(not selftest_gap(standalone.stdout), "standalone frozen selftest omitted required checks")
        installer = (bootstrap if baseline_package == package else
                     extract_bootstrap(baseline_package, scratch / "baseline-bootstrap"))
        baseline_application = files(installer.parent, exclude_data=True)
        first_destination = scratch / "first-install-interrupted"
        first_arguments = ["--install", str(first_destination), "--package", str(baseline_package),
                           "--expected-sha256", baseline_sha]
        interrupted_install = subprocess.run(
            [str(installer), *first_arguments, "--test-fail-after", "active_moved"],
            env=environment, cwd=scratch, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
        )
        require(interrupted_install.returncode == 70,
                "first-install fault did not stop at its intended boundary: " + interrupted_install.stderr[-1600:])
        first_journal = first_destination / "Atlas.update-state.json"
        require(first_journal.is_file(), "interrupted first install retained no journal")
        first_state = json.loads(first_journal.read_text(encoding="utf-8"))
        require(first_state.get("had_active") is False and first_state.get("phase") == "active_moved",
                "first-install recovery journal does not identify the missing-active first installation")
        require(not (first_destination / "Atlas" / "Atlas.exe").exists(),
                "first-install active_moved fault left an active executable")
        run(installer, first_arguments, environment, scratch)
        first_active = first_destination / "Atlas"
        require(files(first_active, exclude_data=True) == baseline_application,
                "external bootstrap did not recover the exact first-installed application")
        require(not first_journal.exists(), "completed first-install recovery retained its journal")
        first_data = first_active / "data"
        require(first_data.is_dir() and not any(first_data.iterdir()),
                "first-install recovery did not retain an empty data directory")
        destination = scratch / "any-folder-install"
        install_arguments = ["--install", str(destination), "--package", str(baseline_package),
                             "--expected-sha256", baseline_sha]
        run(installer, install_arguments, environment, scratch)
        active = destination / "Atlas"
        executable = active / "Atlas.exe"
        expected_application = files(bootstrap.parent, exclude_data=True)
        require(files(active, exclude_data=True) == baseline_application, "first install differs from baseline package")
        seed_database(executable, environment, scratch)
        data = active / "data"
        (data / "desktop-preservation-canary.txt").write_bytes(b"synthetic portable data preservation canary\n")
        database = data / "assesshub.db"
        baseline = database_state(database)
        baseline_files = files(data)
        run(executable, ["--selftest", "--db", str(database)], environment, scratch, timeout=180)
        require(database_state(database) == baseline, "frozen selftest mutated the installed database")

        before_refusal = files(destination)
        rejected = subprocess.run([str(executable), "--update", str(package), "--expected-sha256", "0" * 64],
                                  env=environment, cwd=scratch, capture_output=True, timeout=300, check=False)
        require(rejected.returncode != 0, "incorrect package hash was accepted")
        require(files(destination) == before_refusal, "hash refusal modified active application or data")

        update_arguments = ["--update", str(package), "--expected-sha256", expected_sha]
        # When PR2 provides the exact reviewed PR1 ZIP, this is a genuine installed
        # old-verifier -> new-dependency update, followed by rollback to the old code.
        maintenance(executable, update_arguments, environment, scratch)
        verify_slot(destination)
        require(files(active, exclude_data=True) == expected_application, "update did not activate candidate code")
        require(files(destination / "Atlas.previous", exclude_data=True) == baseline_application,
                "update did not retain the installed baseline in its rollback slot")
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "baseline-to-candidate update changed client data")
        maintenance(executable, ["--rollback"], environment, scratch)
        require(files(active, exclude_data=True) == baseline_application, "rollback did not reactivate baseline code")
        require(database_state(database) == baseline, "baseline rollback changed client data")
        # Start interruption drills from candidate B, so their rollback expectation
        # remains B even when the earlier baseline installation was a distinct A.
        maintenance(executable, update_arguments, environment, scratch)
        verify_slot(destination)
        require(files(active, exclude_data=True) == expected_application,
                "candidate was not established before interruption drills")
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "candidate preparation changed baseline data")
        maintenance(executable, [*update_arguments, "--test-fail-after", "activated"],
                    environment, scratch, expected_code=70)
        journal = destination / "Atlas.update-state.json"
        require(journal.is_file(), "injected update interruption left no recoverable journal")
        require(json.loads(journal.read_text(encoding="utf-8"))["phase"] == "activated",
                "update did not reach the selected interruption boundary")
        maintenance(executable, update_arguments, environment, scratch)
        verify_slot(destination)
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "recovered update changed stored snapshot rows or bytes")
        maintenance(executable, ["--rollback"], environment, scratch)
        require(not journal.exists(), "ordinary rollback retained its journal")
        require(files(active, exclude_data=True) == expected_application, "ordinary rollback changed packaged code")
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "ordinary rollback changed the client database")

        # At active_moved the public executable is deliberately absent. Recovery
        # must still use the durable copy of installed code selected by its pointer.
        maintenance(executable, [*update_arguments, "--test-fail-after", "active_moved"],
                    environment, scratch, expected_code=70)
        require(not executable.exists(), "active_moved fault did not remove the active executable")
        require(journal.is_file() and json.loads(journal.read_text(encoding="utf-8"))["phase"] == "active_moved",
                "missing-active fault did not retain its exact journal phase")
        maintenance(recovery_helper(destination), ["--recover", str(destination)], environment, scratch)
        verify_slot(destination)
        require(files(active, exclude_data=True) == expected_application, "missing-active recovery changed candidate code")
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "missing-active recovery changed the stored database")

        maintenance(executable, ["--rollback", "--test-fail-after", "rollback_active_moved"],
                    environment, scratch, expected_code=70)
        require(not executable.exists(), "rollback_active_moved fault left an active executable")
        require(journal.is_file() and json.loads(journal.read_text(encoding="utf-8"))["phase"] == "rollback_active_moved",
                "interrupted rollback did not retain its exact journal phase")
        maintenance(recovery_helper(destination), ["--recover", str(destination)], environment, scratch)
        require(not journal.exists(), "recovered rollback retained its journal")
        require(files(active, exclude_data=True) == expected_application, "missing-active rollback changed packaged code")
        unchanged_data(baseline_files, data)
        require(database_state(database) == baseline, "missing-active rollback changed stored client data")

        maintenance(executable, update_arguments, environment, scratch)
        verify_slot(destination)
        seed_database(executable, environment, scratch)
        newer = database_state(database)
        require(len(newer["rows"]) > len(baseline["rows"]) and newer["sha256"] != baseline["sha256"],
                "database restore proof did not create newer real application data")
        maintenance(executable, ["--rollback", "--restore-pre-update-database"], environment, scratch)
        require(database_state(database) == baseline, "explicit database rollback failed to restore exact baseline")
        require(not journal.exists(), "database rollback retained its journal")
        archives = list((data / "release-backups").glob("rollback-preserved-*.db"))
        require(any(digest(path) == newer["sha256"] for path in archives),
                "database rollback did not archive the exact newer client database")
        unchanged_data(baseline_files, data)
        require(files(active, exclude_data=True) == expected_application, "rollback changed immutable application members")
        run(executable, ["--selftest", "--db", str(database)], environment, scratch, timeout=180)
        require(database_state(database) == baseline, "final selftest mutated the restored client database")
        unchanged_data(baseline_files, data)
        require(files(active, exclude_data=True) == expected_application, "final selftest mutated installed code")
    return {"schema": "atlas.desktop-no-python-proof/1", "status": "PASS", "zip_sha256": expected_sha,
            "baseline_zip_sha256": baseline_sha,
            "cross_package_update": "PASS" if baseline_sha != expected_sha else "same_candidate_roundtrip_only",
            "python_lookup": "absent_from_child_environment", "working_directory": "external_to_repository",
            "four_step_smoke": "canonical_portable.build_atlas.smoke",
            "first_install_missing_active_recovery": "PASS",
            "interruption_phases": ["activated", "active_moved", "rollback_active_moved"],
            "install_update_interruption_recovery_rollback_database_restore": "PASS",
            "qualification_limit": "host interpreter remains installed; disconnected Python-free host remains external"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--baseline-package", type=Path,
                        help="reviewed previous maintenance-capable ZIP, with its published SHA256SUMS beside it")
    args = parser.parse_args()
    result = prove(args.release_dir.resolve(strict=True), baseline_package=args.baseline_package)
    args.json_out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
