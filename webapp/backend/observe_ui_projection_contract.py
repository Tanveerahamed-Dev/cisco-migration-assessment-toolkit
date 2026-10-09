"""Hosted canonical contract review material; never accepts or rewrites audit pins.

The ordinary API-byte and native-schema guards still run against committed source.
This diagnostic makes a schema-changing bootstrap reviewable even when those guards
correctly fail. Producer hashes are observations, not independent custody receipts.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time

MAX_FILE = 64 * 1024 * 1024
MAX_SOURCE = 512 * 1024 * 1024
MAX_FILES = 10000
OUTPUT_NAMES = frozenset({"source-before.json", "source-after.json", "openapi.json", "openapi.ts",
                          "view-schema.json", "list-schema.json", "observation.json"})


def need(ok, message):
    if not ok:
        raise ValueError(message)


def run(root, args, timeout=60):
    # Bound while collecting, not after communicate() has already allocated arbitrary output.
    process = subprocess.Popen(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=os.name == "posix")
    events = queue.Queue(maxsize=4)
    stopped = threading.Event()

    def consume(index, stream):
        while not stopped.is_set():
            raw = stream.read1(65536)
            while not stopped.is_set():
                try:
                    events.put((index, raw), timeout=0.1)
                    break
                except queue.Full:
                    pass
            if not raw:
                break

    readers = [threading.Thread(target=consume, args=(index, stream), daemon=True)
               for index, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    buffers = [bytearray(), bytearray()]
    total = 0
    ended = set()
    completed = False
    try:
        while len(ended) != 2:
            remaining = deadline - time.monotonic()
            need(remaining > 0, "Command exceeded time bound")
            try:
                index, raw = events.get(timeout=remaining)
            except queue.Empty as error:
                raise ValueError("Command exceeded time bound") from error
            total += len(raw)
            need(total <= MAX_FILE, "Command output exceeds review bound")
            if raw:
                buffers[index].extend(raw)
            else:
                ended.add(index)
        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        completed = True
        need(code == 0, "Command failed: " + args[0] + " " + buffers[1][-4096:].decode("utf-8", "replace"))
        return bytes(buffers[0])
    finally:
        stopped.set()
        if not completed and os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif not completed and process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            stream.close()


def git(root, *args):
    return run(root, ["git", "--no-optional-locks", *args])


def ordinary(path):
    need(path.absolute() == path.resolve(), "Indirect file path")
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_FILE,
             "Nonordinary or oversized file")
        raw = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
    need(len(raw) == before.st_size and
         (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
         (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "File changed while read")
    return raw


def emit(output, name, raw):
    need(name in OUTPUT_NAMES and len(raw) <= MAX_FILE, "Unknown or oversized review member")
    need(output.absolute() == output.resolve(), "Indirect review directory")
    with (output / name).open("xb") as stream:
        stream.write(raw)


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()


def source_identity(root, expected):
    need(re.fullmatch(r"[0-9a-f]{40}", expected or ""), "Exact hosted source SHA required")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    need(head == expected, "Hosted source differs from expected execution SHA")
    need(not git(root, "status", "--porcelain=v1", "--untracked-files=all"), "Checkout is not clean")
    tracked = git(root, "ls-tree", "-rz", "HEAD").split(b"\0")[:-1]
    need(0 < len(tracked) <= MAX_FILES, "Tracked source census exceeds bound")
    materials = {}
    total = 0
    for entry in tracked:
        meta, name = entry.split(b"\t", 1)
        mode, kind, blob = meta.decode("ascii").split()
        path = name.decode("utf-8", "strict")
        need(mode in ("100644", "100755") and kind == "blob", "Nonregular tracked input")
        raw = ordinary(root / path)
        total += len(raw)
        need(total <= MAX_SOURCE, "Tracked source byte census exceeds bound")
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        need(actual == blob, "Physical source differs from committed bytes: " + path)
        executable = bool((root / path).stat().st_mode & stat.S_IXUSR)
        need(executable == (mode == "100755"), "Physical source mode differs: " + path)
        materials[path] = {"mode": mode, "git_blob": blob, "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()}
    return {"commit": head, "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
            "parents": git(root, "show", "-s", "--format=%P", "HEAD").decode().strip().split(),
            "materials": materials}


def schema_bytes(schema, owner_hash):
    raw = (json.dumps(schema, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
    observed = hashlib.sha256(raw).hexdigest()
    need(owner_hash(schema) == observed, "Native owner hash and retained schema representation differ")
    return raw, observed


def main():
    need(len(sys.argv) == 1, "Fixed diagnostic takes no source/path/hash arguments")
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
         and os.environ.get("RUNNER_OS") == "Linux" and os.environ.get("GITHUB_JOB") == "frontend",
         "GitHub-hosted frontend Linux execution required")
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ["RUNNER_TEMP"]).resolve() / "ui-projection-contract"
    need(not output.exists() and not output.is_relative_to(root), "Fresh outside-checkout review directory required")
    output.mkdir(mode=0o700)
    expected = os.environ.get("GITHUB_SHA", "")
    report = {"schema": "ui_projection_contract_review/1", "status": "INCOMPLETE_OR_FAILED",
              "run_id": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
              "job": os.environ["GITHUB_JOB"], "errors": [],
              "limits": ["Review material only; hashes do not certify their own schemas.",
                         "Committed API types, literal native pins and all ordinary guards remain unchanged.",
                         "Not independent archive custody, release or semantic acceptance."]}
    before = None
    try:
        before = source_identity(root, expected)
        emit(output, "source-before.json", encoded(before))
        # Import actual committed owners only in the hosted runner, after source binding.
        sys.path.insert(0, str(root))
        from webapp.backend import ui_projection_api as api
        from webapp.backend.export_ui_projection_openapi import export_schema

        exported = (json.dumps(export_schema(), indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n").encode("utf-8")
        need(ordinary(root / "webapp/frontend/.generated/openapi.json") == exported,
             "Generator input differs from fresh real-app export")
        emit(output, "openapi.json", exported)
        pins = {}
        for kind, schema in (("view", api._VIEW_SCHEMA), ("list", api._LIST_SCHEMA)):
            raw, digest = schema_bytes(schema, api._native_schema_hash)
            emit(output, kind + "-schema.json", raw)
            pins[kind] = {"observed_sha256": digest, "declared_pin": api._NATIVE_SCHEMA_HASHES[kind],
                          "matches_declared_pin": digest == api._NATIVE_SCHEMA_HASHES[kind]}
        report["native_pins"] = pins
        run(root, ["node", "webapp/frontend/scripts/generate-api-types.mjs", "--review"], timeout=180)
        generated = ordinary(output / "openapi.ts")
        report["generated_types_match_committed"] = generated == ordinary(root / "webapp/frontend/src/generated/openapi.ts")
        report["tools"] = {"python": sys.version, "node": run(root, ["node", "--version"]).decode().strip(),
                           "npm": run(root, ["npm", "--version"]).decode().strip(),
                           "python_packages": {name: version(name) for name in
                                               ("jsonschema-rs", "jsonschema", "fastapi", "pydantic")},
                           "pip_freeze": run(root, [sys.executable, "-m", "pip", "freeze", "--all"]).decode().splitlines(),
                           "npm_ls": json.loads(run(root / "webapp/frontend", ["npm", "ls", "--all", "--json"]))}
        report["status"] = "OBSERVED_REVIEW_REQUIRED"
    except Exception as error:
        report["errors"].append(str(error))
    finally:
        try:
            after = source_identity(root, expected)
            emit(output, "source-after.json", encoded(after))
            need(before is not None and before == after, "Source changed during contract observation")
        except Exception as error:
            report["errors"].append("Closing source guard: " + str(error))
        report["members"] = {}
        try:
            for path in sorted(output.iterdir()):
                need(path.name in OUTPUT_NAMES - {"observation.json"}, "Unexpected review member")
                raw = ordinary(path)
                report["members"][path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if not report["errors"]:
                need(set(report["members"]) == OUTPUT_NAMES - {"observation.json"}, "Missing review member")
        except Exception as error:
            report["errors"].append("Closing output guard: " + str(error))
        if report["errors"]:
            report["status"] = "INCOMPLETE_OR_FAILED"
        emit(output, "observation.json", encoded(report))
    print(json.dumps({"status": report["status"], "native_pins": report.get("native_pins"), "errors": report["errors"]}))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
